"""Quản lý rủi ro danh mục: cài đặt vốn/ngưỡng, lệnh đang giữ theo luật bán, tổng rủi ro mở và tỷ trọng ngành.

Rủi ro mở của một lệnh = số cp còn giữ × (giá hiện tại − cắt lỗ hiện tại): số tiền mất thêm nếu mọi lệnh
cùng về cắt lỗ. Giá trong DB là nghìn đồng."""
import json

from ..fmt import num
from .data import get_ohlcv
from .positions import simulate

DEFAULTS = dict(capital=100.0,      # vốn, triệu đồng
                risk_pct=1.0,       # % vốn chấp nhận mất mỗi lệnh
                max_heat=6.0,       # tổng rủi ro mở tối đa, % vốn
                max_pos=6,          # số lệnh mở tối đa
                max_sector=40.0)    # tỷ trọng tối đa một ngành, % giá trị đang giữ
LIGHT_FACTOR = {"green": 1.0, "yellow": 0.5, "red": 0.0}   # hệ số % rủi ro gợi ý theo đèn thị trường
RED_HEAT = 3.0                       # đèn đỏ mà rủi ro mở vượt mức này (% vốn) thì nhắc giảm


def _n(x) -> str:
    """6.3 -> '6,3' ; 40.0 -> '40' (kiểu Việt Nam, bỏ ,0)."""
    s = num(float(x), 1)
    return s[:-2] if s.endswith(",0") else s


def get_settings(conn) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key='risk'").fetchone()
    saved = json.loads(row[0]) if row else {}
    return {k: type(v)(saved.get(k, v)) for k, v in DEFAULTS.items()}


def put_settings(conn, upd: dict) -> dict:
    """Ghi các khóa hợp lệ (số dương); trả cài đặt sau khi ghi."""
    cur = get_settings(conn)
    for k, v in upd.items():
        if k in DEFAULTS and v is not None:
            v = type(DEFAULTS[k])(v)
            if v <= 0:
                raise ValueError(f"{k} phải > 0")
            cur[k] = v
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('risk', ?)", (json.dumps(cur),))
    conn.commit()
    return cur


def open_positions(conn) -> list[dict]:
    """Lệnh đang giữ, kèm trạng thái theo luật bán (cắt lỗ hiện tại, mục tiêu kế tiếp, việc cần làm)."""
    out = []
    for row in conn.execute("SELECT * FROM positions WHERE status='open' ORDER BY entry_d DESC, id DESC").fetchall():
        p = dict(row, targets=json.loads(row["targets"] or "[]"))
        p["sold"] = conn.execute("SELECT COALESCE(sum(qty),0) FROM sales WHERE pos_id=?", (p["id"],)).fetchone()[0]
        bars = [r for r in get_ohlcv(conn, p["sym"], 4000, refresh=False) if r["d"] >= p["entry_d"]]
        if bars:
            s = simulate(p["entry_px"], p["stop"], p["targets"], bars)
            p.update(c=bars[-1]["c"], d=bars[-1]["d"], days=len(bars) - 1,
                     pnl=round((bars[-1]["c"] / p["entry_px"] - 1) * 100, 1),
                     cur_stop=s["stop"], left=s["left"], hit=s["hit"], next=s["next"], pending=s["pending"],
                     sold_out=None if s["open"] else s["exits"][-1]["d"], events=s["events"][-3:])
        out.append(p)
    return out


def portfolio_risk(positions: list[dict], settings: dict, sector_of: dict, light: str | None) -> dict:
    """Tổng hợp rủi ro danh mục. sector_of: {mã: tên ngành}. Lệnh chưa nhập số lượng thì không tính được tiền."""
    cap = settings["capital"] * 1e6
    items, by_sector, no_qty = [], {}, []
    for p in positions:
        c, stop = p.get("c"), p.get("cur_stop") or p["stop"]
        if p.get("qty") is None or c is None:
            no_qty.append(p["sym"]); continue
        held = max(0, p["qty"] - p.get("sold", 0))
        if held == 0:
            continue
        risk = max(0.0, (c - stop) * 1000 * held)
        value = c * 1000 * held
        sec = sector_of.get(p["sym"]) or "Khác"
        by_sector[sec] = by_sector.get(sec, 0) + value
        items.append(dict(id=p["id"], sym=p["sym"], held=held, risk=round(risk), risk_pct=round(risk / cap * 100, 2),
                          value=round(value), sector=sec, below_stop=c < stop))
    total_risk = sum(x["risk"] for x in items)
    total_value = sum(x["value"] for x in items)
    heat = total_risk / cap * 100 if cap else 0
    sectors = sorted(({"name": k, "value": round(v), "pct": round(v / total_value * 100, 1) if total_value else 0}
                      for k, v in by_sector.items()), key=lambda x: -x["value"])
    warn = []
    if heat > settings["max_heat"]:
        warn.append(f"Tổng rủi ro mở {_n(heat)}% vốn, vượt ngưỡng {_n(settings['max_heat'])}%: không mở thêm lệnh, cân nhắc giảm.")
    if len(positions) > settings["max_pos"]:
        warn.append(f"Đang giữ {len(positions)} lệnh, vượt ngưỡng {settings['max_pos']} lệnh.")
    for s in sectors:
        if s["pct"] > settings["max_sector"] and len(items) > 1:
            warn.append(f"Ngành {s['name']} chiếm {_n(s['pct'])}% giá trị danh mục (ngưỡng {_n(settings['max_sector'])}%).")
    if light == "red" and heat > RED_HEAT:
        warn.append(f"Đèn đỏ mà rủi ro mở còn {_n(heat)}% vốn: backtest cho thấy đèn đỏ có kỳ vọng âm, nên siết cắt lỗ hoặc giảm.")
    for x in items:
        if x["below_stop"]:
            warn.append(f"{x['sym']} đang dưới cắt lỗ: xem việc cần làm ở bảng Danh mục.")
    return dict(capital=settings["capital"], heat=round(heat, 2), max_heat=settings["max_heat"],
                total_risk=round(total_risk), total_value=round(total_value), n=len(positions),
                max_pos=settings["max_pos"], items=items, sectors=sectors, no_qty=no_qty,
                light=light, factor=LIGHT_FACTOR.get(light or "", 1.0), warnings=warn)
