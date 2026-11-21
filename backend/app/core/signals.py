"""Sinh tín hiệu cuối ngày từ kết quả analyse() hôm nay + kết quả lần quét trước, và việc cần làm với lệnh đang giữ."""
from ..config import MIN_LIQ_BIL
from ..fmt import price as _p, num, pct, day
from .plan import LPS_HOLD
from .positions import simulate

# thứ tự ưu tiên khi xếp hạng / chọn ảnh gửi Telegram (việc với danh mục đang giữ lên đầu)
PRIORITY = {"Cắt lỗ": -4, "Hết thời gian": -3, "Chốt lời": -2, "Dời cắt lỗ": -1,
            "LPS": 0, "SOS mới": 1, "Spring": 2, "Tiềm năng sớm": 3, "D sớm": 4,
            "Chốt lời?": 7, "Rời Pha D": 8, "Gãy hỗ trợ": 9, "UTAD": 10}
ICON = {"Cắt lỗ": "⛔", "Hết thời gian": "⏱", "Chốt lời": "💰", "Dời cắt lỗ": "🔼",
        "LPS": "✅", "SOS mới": "🚀", "Spring": "🌱", "Tiềm năng sớm": "🔭", "D sớm": "👀",
        "Chốt lời?": "💰", "Rời Pha D": "⚠️", "Gãy hỗ trợ": "⛔", "UTAD": "🔻"}
READY_MIN = 70        # điểm sẵn sàng tối thiểu để báo "Tiềm năng sớm"
READY_BUY = 60        # điểm tối thiểu cho mọi tín hiệu mua: backtest 2019–2026 điểm < 60 có R TB −0,34 (Spring gần như đều < 60)
BUY = ("LPS", "SOS mới", "Spring", "Tiềm năng sớm", "D sớm")
# tín hiệu mua bị ẩn theo màu đèn. Chọn trên backtest 2019–2023, kiểm tra 2024–2026 (R TB):
# đèn đỏ mọi loại âm; đèn vàng LPS −0,09/−0,21 và D sớm −0,10/−0,37, còn Tiềm năng sớm +0,45/+0,16.
HIDE = {"red": BUY, "yellow": ("LPS", "D sớm")}


def plan_text(p: dict | None) -> str:
    """'vào 31.185–33.114 · cắt lỗ 29.919 (−6,9%) · mục tiêu 42.000 (+30,6%) · lời/lỗ 4,4'"""
    if not p or not p.get("entry_lo"):
        return ""
    s = f"vào {_p(p['entry_lo'])}–{_p(p['entry_hi'])}"
    if p.get("stop"):
        s += f" · cắt lỗ {_p(p['stop'])} ({pct(p['risk_pct'])})"
    main = next((t for t in p.get("targets", []) if t["k"] == p.get("main_target")), None)
    if main:
        s += f" · mục tiêu {_p(main['price'])} ({pct(main['pct'])}) · lời/lỗ {num(p['rr'], 1)}"
    return s


def build(sym: str, r: dict, prev: dict | None, in_watchlist: bool) -> list[dict]:
    out = []
    if not r or r.get("tag") in (None, "mới tạo đáy"):
        return out
    liquid = r["liq"] >= MIN_LIQ_BIL
    p = r.get("plan") or {}
    today = r["d"]
    add = lambda kind, text: out.append(dict(sym=sym, kind=kind, text=text))
    pt = plan_text(p)
    ready = (p.get("ready") or {}).get("score", 0)

    if liquid and not r.get("weak_drop") and ready >= READY_BUY:
        # LPS chỉ báo khi giá đã giữ đáy LPS ít nhất LPS_HOLD phiên (đáy hôm nay là giá còn đang giảm)
        if r["tag"] == "D-LPS" and (r.get("vx") or 9) < 1.0 and (r.get("lps_age") or 0) >= LPS_HOLD:
            add("LPS", f"{sym} {_p(r['c'])} · {pt}")
        sos = r.get("sos")
        if sos and sos["d"] == today:
            add("SOS mới", f"{sym} {_p(r['c'])} · vượt trần {_p(r['range']['res'])} KL x{num(sos['vx'], 1)} · "
                           f"chờ Backup: {pt}")
        sup = r["range"]["sup"]
        for e in r["events"]:
            if e["d"] != today or r["c"] < sup or r["stage"] == "failed":
                continue
            vx = e["vx"] or 9
            # Spring: thủng đáy SC rồi đóng lại trên đáy, KL dưới TB20
            # ST: chạm trong 2% quanh đáy với KL rất thấp (cung cạn rõ)
            if (e["k"] == "Spring" and vx < 1.0) or (e["k"] == "ST" and e["price"] <= sup * 1.02 and vx < 0.7):
                add("Spring", f"{sym} {_p(r['c'])} · {e['k']} về {_p(e['price'])} KL x{num(vx, 1)} · {pt}")
        if r["tag"] == "D sớm" and (not prev or prev.get("tag") != "D sớm"):
            add("D sớm", f"{sym} {_p(r['c'])} · {r['extra']} · điểm {ready} · {pt}")
        elif r["stage"] in ("BC", "near") and ready >= READY_MIN and (r.get("dist") or -99) >= -8:
            add("Tiềm năng sớm", f"{sym} {_p(r['c'])} · điểm {ready} · cách trần {pct(r['dist'])} · {pt}")

    # đang có lời mà xuất hiện cung -> cân nhắc chốt lời một phần
    if r.get("supply") and (r["stage"] in ("D", "E") or in_watchlist):
        add("Chốt lời?", f"{sym} {_p(r['c'])} · KL x{num(r.get('vx') or 0, 1)} nhưng đóng gần đáy phiên: dấu hiệu cung")

    # cảnh báo cho mã đang theo dõi hoặc vừa ở Pha D
    if prev and (in_watchlist or prev.get("stage") == "D"):
        if prev.get("stage") == "D" and r["stage"] in ("failed", "BC"):
            add("Rời Pha D", f"{sym} {_p(r['c'])} · {prev.get('tag')} → {r['tag']}")
        pstop = (prev.get("plan") or {}).get("stop") or (prev.get("levels") or {}).get("invalid")
        if pstop and r["c"] < pstop <= prev.get("c", 0):
            add("Gãy hỗ trợ", f"{sym} {_p(r['c'])} · thủng mốc cắt lỗ {_p(pstop)}")
    # phân phối: chỉ UTAD có tác dụng trong kiểm chứng 2019–2026 (10 phiên sau kém TB 0,5–0,9 điểm %, yếu);
    # SOW/LPSY không khác trung bình nên chỉ hiển thị trên web, không báo
    dd = r.get("distrib") or {}
    if in_watchlist and any(e["k"] == "UTAD" and e["d"] == today for e in dd.get("events", [])):
        add("UTAD", f"{sym} {_p(r['c'])} · vượt đỉnh {_p(dd['top'])} rồi đóng cửa dưới: dấu hiệu phân phối, cân nhắc siết cắt lỗ")
    for s in out:
        s["prio"] = PRIORITY[s["kind"]]; s["rs20"] = r.get("rs20")
    return out


def position_alerts(sym: str, positions: list[dict], bars: list[dict], rs20=None) -> list[dict]:
    """Việc cần làm trong phiên cuối của `bars` với các lệnh đang giữ của một mã (luật ở positions.simulate).
    positions: dict(entry_d, entry_px, stop, targets=[...]); bars: OHLCV của mã, phủ từ ngày mua.
    Mỗi loại một dòng vì khóa bảng signals là (date, sym, kind)."""
    today, texts = bars[-1]["d"], {}
    for p in positions:
        s = simulate(p["entry_px"], p["stop"], p["targets"], [b for b in bars if b["d"] >= p["entry_d"]])
        for e in s["events"]:
            if e["d"] == today:
                texts.setdefault(e["kind"], []).append(f"mua {day(p['entry_d'])} giá {_p(p['entry_px'])}: {e['text']}")
    return [dict(sym=sym, kind=k, text=f"{sym} {_p(bars[-1]['c'])} · " + "; ".join(t), prio=PRIORITY[k], rs20=rs20)
            for k, t in texts.items()]
