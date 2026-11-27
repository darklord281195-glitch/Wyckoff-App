"""Sổ lệnh thử nghiệm: app tự "mua" lúc 14h10–14h29 khi mã đạt kịch bản mua đẹp (intraday.auto_buy), rồi tự bán
theo đúng luật (positions.simulate: cắt lỗ, chốt T1/T2, dời cắt lỗ, hết 20 phiên). Không có lệnh thật, không đụng
Danh mục. Mục đích: đo điểm mua nào đúng / sai theo từng điều kiện để chỉnh luật quét (và skill wyckoff).

Kết quả không lưu: mỗi lần xem tính lại từ phiên mua, nên luật bán đổi thì kết quả cũ cũng đổi theo.

  .venv\\Scripts\\python -m app.core.paper      # in báo cáo theo loại kế hoạch / đèn / KL / lời/lỗ
"""
import datetime as dt
import json

from .data import get_ohlcv
from .positions import simulate

BUY_FEE, SELL_FEE, SLIP = 0.0015, 0.0025, 0.0025    # cùng mức với backtest
# nhóm để so sánh: (tên, hàm lấy nhóm từ một lệnh)
GROUPS = (
    ("Loại kế hoạch", lambda x: x["kind"] or "–"),
    ("Đèn lúc mua", lambda x: {"green": "xanh", "yellow": "vàng", "red": "đỏ"}.get(x["light"], "?")),
    ("KL đã khớp / TB20", lambda x: "< x0,5" if x["vx"] < 0.5 else "x0,5–0,7" if x["vx"] < 0.7 else "≥ x0,7"),
    ("Lời/lỗ kế hoạch", lambda x: "2–3" if x["rr"] < 3 else "3–5" if x["rr"] < 5 else "≥ 5"),
    ("Vị trí giá trong phiên", lambda x: "nửa trên" if x["close_pos"] < 0.8 else "sát đỉnh (≥ 80%)"),
)


def record(conn, rows: list[dict]) -> int:
    """rows: dict(d, at, sym, kind, entry_px, stop, targets=[...], light, rr, vx, close_pos, why, plan). Trùng (ngày, mã) bỏ qua."""
    n = 0
    for r in rows:
        n += conn.execute(
            "INSERT OR IGNORE INTO paper_trades(d,at,sym,kind,entry_px,stop,targets,light,rr,vx,close_pos,why,plan) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["d"], r["at"], r["sym"], r["kind"], r["entry_px"], r["stop"], json.dumps(r["targets"]), r["light"],
             r["rr"], r["vx"], r["close_pos"], r["why"], json.dumps(r["plan"], ensure_ascii=False))).rowcount
    conn.commit()
    return n


def _trades(conn):
    return [dict(r, targets=json.loads(r["targets"] or "[]"))
            for r in conn.execute("SELECT * FROM paper_trades ORDER BY d, sym")]


def evaluate(t: dict, bars: list[dict]) -> dict:
    """Kết quả một lệnh thử nghiệm theo luật bán. bars: OHLCV đã chốt từ phiên mua (bars[0] = phiên mua)."""
    bars = [b for b in bars if b["d"] >= t["d"]]
    if not bars or bars[0]["d"] != t["d"]:
        return dict(status="chờ dữ liệu", R=None, exit_d=None, exit_why=None, days=0, events=[])
    s = simulate(t["entry_px"], t["stop"], t["targets"], bars)
    last = bars[-1]["c"]
    value = (sum(e["frac"] * e["px"] for e in s["exits"]) + s["left"] * last) * (1 - SELL_FEE - SLIP)
    cost = t["entry_px"] * (1 + BUY_FEE + SLIP)
    return dict(status="đang giữ" if s["open"] else "đã đóng",
                R=round((value - cost) / max(t["entry_px"] - t["stop"], t["entry_px"] * 1e-3), 2),
                exit_d=None if s["open"] else s["exits"][-1]["d"], exit_why=None if s["open"] else s["exits"][-1]["why"],
                hit_t1=s["hit"] > 0, days=len(bars) - 1, cur_stop=s["stop"], events=s["events"])


def _stats(xs):
    closed = [x for x in xs if x["status"] == "đã đóng"]
    n = len(closed)
    return dict(n=len(xs), closed=n, open=sum(x["status"] == "đang giữ" for x in xs),
                win=round(100 * sum(x["R"] > 0 for x in closed) / n) if n else None,
                stop=round(100 * sum(x["exit_why"] in ("Cắt lỗ", "Thủng cắt lỗ dời") for x in closed) / n) if n else None,
                avg_r=round(sum(x["R"] for x in closed) / n, 2) if n else None)


def score(conn) -> dict:
    """Mọi lệnh thử nghiệm kèm kết quả + tổng hợp chung và theo từng nhóm điều kiện (để biết luật nào cần sửa)."""
    cache, items = {}, []
    for t in _trades(conn):
        bars = cache.setdefault(t["sym"], get_ohlcv(conn, t["sym"], 4000, refresh=False))
        items.append(dict({k: t[k] for k in ("id", "d", "at", "sym", "kind", "entry_px", "stop", "targets", "light",
                                              "rr", "vx", "close_pos", "why")}, **evaluate(t, bars)))
    groups = []
    for name, key in GROUPS:
        by = {}
        for x in items:
            by.setdefault(key(x), []).append(x)
        groups.append(dict(name=name, rows=[dict(label=k, **_stats(v)) for k, v in sorted(by.items())]))
    for x in items:
        x["events"] = x["events"][-3:]
    return dict(summary=_stats(items), groups=groups, items=items[::-1])


def events_on(conn, d: str) -> list[str]:
    """Việc luật bán làm trong phiên d với các lệnh thử nghiệm (cho tin Telegram cuối ngày)."""
    out, cache = [], {}
    for t in _trades(conn):
        if t["d"] > d:
            continue
        bars = [b for b in cache.setdefault(t["sym"], get_ohlcv(conn, t["sym"], 4000, refresh=False)) if b["d"] <= d]
        for e in evaluate(t, bars)["events"]:
            if e["d"] == d:
                out.append(f"{t['sym']} (mua {t['d'][8:]}/{t['d'][5:7]} giá {t['entry_px']:g}): {e['text']}")
    return out


def open_syms(conn) -> set[str]:
    """Mã đang có lệnh thử nghiệm chưa bán hết (không mua chồng)."""
    cache = {}
    return {t["sym"] for t in _trades(conn)
            if evaluate(t, cache.setdefault(t["sym"], get_ohlcv(conn, t["sym"], 4000, refresh=False)))["status"]
            in ("đang giữ", "chờ dữ liệu")}


def report(conn) -> str:
    s = score(conn)
    fmt = lambda st: (f"{st['n']} lệnh, đã đóng {st['closed']}, thắng {st['win'] if st['win'] is not None else '–'}%, "
                      f"cắt lỗ {st['stop'] if st['stop'] is not None else '–'}%, R TB {st['avg_r'] if st['avg_r'] is not None else '–'}")
    lines = ["Sổ lệnh thử nghiệm: " + fmt(s["summary"])]
    for g in s["groups"]:
        lines.append(f"\n{g['name']}:")
        lines += [f"  {r['label']:<28} {fmt(r)}" for r in g["rows"]]
    lines.append("\nLệnh gần nhất:")
    lines += [f"  {x['d']} {x['sym']:<5} {x['kind']:<26} giá {x['entry_px']:g} · {x['status']}"
              + (f" · {x['exit_why']}" if x["exit_why"] else "") + (f" · {x['R']:+.2f}R" if x["R"] is not None else "")
              for x in s["items"][:20]]
    return "\n".join(lines)


def review_data(conn, before: int = 20) -> str:
    """Dữ liệu cho buổi xem lại hằng tuần (scripts/weekly-review): báo cáo nhóm + từng lệnh kèm kế hoạch lúc mua
    và nến từ `before` phiên trước khi mua tới nay, để đọc lại vì sao lệnh thắng / thua."""
    today = dt.date.today()
    last_friday = today.weekday() == 4 and (today + dt.timedelta(days=7)).month != today.month
    out = [f"Hôm nay: {today:%d/%m/%Y} · thứ 6 cuối tháng: {'CÓ – làm mục 7 Tổng kết tháng' if last_friday else 'không'}\n",
           report(conn), "\n\n# Backtest 2019–2026 để so (app.backtest): loại · số lệnh · % chạm T1 · % cắt lỗ · R TB"]
    out += [f"  {r['plan']} · {r['n']} · {r['hit_t1']}% · {r['stop']}% · {r['avg_r']:+.2f}R"
            for r in conn.execute("SELECT plan, n, hit_t1, stop, avg_r FROM backtest_stats ORDER BY n DESC")]
    out.append("\n\n# Chi tiết từng lệnh (nến: ngày O H L C KL-triệu-cp)")
    trades = {t["id"]: t for t in _trades(conn)}
    for x in score(conn)["items"]:
        t = trades[x["id"]]
        bars = get_ohlcv(conn, t["sym"], 4000, refresh=False)
        i = next((k for k, b in enumerate(bars) if b["d"] >= t["d"]), len(bars))
        plan = json.loads(t["plan"] or "{}")
        out.append(f"\n## {t['sym']} mua {t['d']} {t['at']} giá {t['entry_px']:g} · {t['kind']} · {x['status']}"
                   + (f" · {x['exit_why']} {x['exit_d']}" if x["exit_why"] else "") + (f" · {x['R']:+.2f}R" if x["R"] is not None else ""))
        out.append(f"cắt lỗ {t['stop']:g} · mục tiêu {t['targets']} · đèn {t['light']} · lời/lỗ {t['rr']} · KL x{t['vx']} · "
                   f"vị trí giá {t['close_pos']} · {t['why']}")
        out.append("kế hoạch: " + " | ".join(str(plan.get(k)) for k in ("trigger", "selloff", "ready") if plan.get(k)))
        out.append("sự kiện luật bán: " + "; ".join(f"{e['d']} {e['text']}" for e in x["events"]) if x["events"] else "sự kiện luật bán: –")
        out += [f"  {b['d']} {b['o']:g} {b['h']:g} {b['l']:g} {b['c']:g} {b['v']:.2f}" + (" ← mua" if b["d"] == t["d"] else "")
                for b in bars[max(0, i - before):]]
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    from ..db import connect
    print(review_data(connect()) if "--review" in sys.argv else report(connect()))
