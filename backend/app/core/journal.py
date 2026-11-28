"""Nhật ký giao dịch: so kết quả thật của người dùng với kết quả nếu làm đúng luật, và đánh dấu vi phạm kỷ luật.

R thật   = lãi/lỗ sau phí ÷ rủi ro ban đầu (giá mua − cắt lỗ lúc mua), gồm phần chưa bán tính theo giá hiện tại.
R luật   = cùng điểm mua, bán theo positions.simulate (cắt lỗ, chốt T1/T2, dời cắt lỗ, hết thời gian).
Giá trong DB là nghìn đồng."""
import json

from .positions import simulate
from .plan import TIME_STOP
from ..fmt import price as _p, num

from .costs import BUY_FEE, SELL_FEE     # cùng mức với backtest (mua 0,15%; bán 0,15% + thuế 0,1%)
LATE = 2                                  # bán sau mốc luật quá số phiên này = cắt lỗ trễ
STOP_KINDS = ("Cắt lỗ", "Thủng cắt lỗ dời", "Hết thời gian")


def _r(entry, stop0, fills, left_frac, last_c):
    """R từ các lần bán (frac, px) + phần còn giữ tính theo giá hiện tại."""
    risk = entry - stop0
    if risk <= 0:
        return None
    value = sum(f * px for f, px in fills) * (1 - SELL_FEE) + left_frac * last_c * (1 - SELL_FEE)
    return round((value - entry * (1 + BUY_FEE)) / risk, 2)


def entry_flags(p, plan, light):
    """Cờ lúc mua: mua ngoài vùng vào kế hoạch, mua khi đèn đỏ, kế hoạch lời/lỗ < 2."""
    f = []
    lo, hi = plan.get("entry_lo"), plan.get("entry_hi")
    if not lo or not hi:
        f.append("không có vùng vào")
    elif p["entry_px"] > hi * 1.01:
        f.append("mua cao hơn vùng vào")
    elif p["entry_px"] < lo * 0.99:
        f.append("mua dưới vùng vào")
    if light == "red":
        f.append("mua khi đèn đỏ")
    if plan.get("rr") is not None and plan["rr"] < 2:
        f.append("lời/lỗ kế hoạch < 2")
    return f


def exit_flags(p, sales, rule, days):
    """Cờ lúc bán so với luật. days: các ngày giao dịch từ ngày mua (tăng dần)."""
    f = []
    qty = p.get("qty")
    stop_exit = next((e for e in rule["exits"] if e["why"] in STOP_KINDS), None)
    if stop_exit and stop_exit["d"] in days:
        due = days[min(len(days) - 1, days.index(stop_exit["d"]) + LATE)]
        sold_by_due = sum(s["qty"] or 0 for s in sales if s["d"] <= due)
        still = (qty - sold_by_due) if qty else (0 if any(s["d"] <= due for s in sales) else 1)
        late_day = days.index(stop_exit["d"]) + LATE < len(days) - 1
        if still > 0 and late_day:
            f.append("giữ quá hạn 20 phiên" if stop_exit["why"] == "Hết thời gian" else "cắt lỗ trễ")
    first_rule = rule["exits"][0]["d"] if rule["exits"] else None
    t1 = (p["targets"] or [None])[0]
    if sales and (first_rule is None or sales[0]["d"] < first_rule) and (t1 is None or sales[0]["px"] < t1):
        f.append("bán sớm trước tín hiệu bán")
    return f


LIGHT_FACTOR = {"green": 1.0, "yellow": 0.5, "red": 0.0}
LIGHT_VN = {"green": "xanh", "yellow": "vàng", "red": "đỏ"}
WIDE_STOP = 8.0                           # % khoảng cắt lỗ: xa hơn thường là mua xa điểm vào


def _day(d):
    return f"{d[8:10]}/{d[5:7]}" if d else "–"


def lessons(p, plan, light, setup_fails, sales, rule, days, settings=None, r_real=None, r_rule=None, last_c=None):
    """Điểm sai và cách khắc phục của một lệnh, viết cho người mới: [dict(ok, title, detail, fix)].
    ok=True là điểm làm tốt (không có fix). setup_fails: lý do phiên mua chưa đạt kịch bản mua đẹp (intraday.checklist)."""
    out = []
    bad = lambda t, d, f: out.append(dict(ok=False, title=t, detail=d, fix=f))
    good = lambda t, d: out.append(dict(ok=True, title=t, detail=d, fix=""))
    px, stop0, kind = p["entry_px"], p.get("stop0") or p["stop"], plan.get("kind") or "–"
    lo, hi = plan.get("entry_lo"), plan.get("entry_hi")
    n_bad = 0
    # ---- lúc mua
    if not lo or not hi:
        bad("Mua khi kế hoạch chưa có điểm mua",
            f"Ngày mua {_day(p['entry_d'])}, kế hoạch theo luật hiện tại là “{kind}”, chưa có vùng mua"
            + (f" (lúc bạn ghi nhận, app ghi “{p['kind']}”; luật đã được chỉnh sau đó)" if p.get("kind") and p["kind"] != kind else "")
            + ".",
            "Chỉ mua khi thẻ Kế hoạch giao dịch có vùng mua và bảng Kiểm tra trước khi mua báo “Nên vào”.")
    elif px > hi * 1.01:
        bad("Mua đuổi, cao hơn vùng mua",
            f"Mua {_p(px)}, vùng mua {_p(lo)}–{_p(hi)}: cao hơn cận trên {num((px / hi - 1) * 100, 1)}%.",
            "Đặt lệnh LO trong vùng mua; giá đã vượt cận trên thì bỏ qua, chờ nhịp lùi (LPS/Backup).")
    elif px < lo * 0.99:
        bad("Mua dưới vùng mua",
            f"Mua {_p(px)}, vùng mua {_p(lo)}–{_p(hi)}: giá đã rơi khỏi vùng, gần cắt lỗ.",
            "Giá rơi dưới vùng mua là kịch bản đang yếu đi: chờ phiên quay đầu trong vùng rồi mới mua.")
    else:
        good("Mua trong vùng mua", f"Mua {_p(px)}, vùng {_p(lo)}–{_p(hi)}.")
    if light == "red":
        bad("Mua khi đèn thị trường đỏ",
            "Đèn VNINDEX đỏ ngày mua: backtest cho thấy lệnh mở khi đèn đỏ có kỳ vọng âm.",
            "Đèn đỏ không mở lệnh mới; đèn vàng chỉ dùng ½ mức rủi ro mỗi lệnh.")
    if plan.get("rr") is not None and plan["rr"] < 2:
        bad("Kế hoạch lời/lỗ dưới 2", f"Lời/lỗ của kế hoạch chỉ {num(plan['rr'], 1)}: thắng không đủ bù thua.",
            "Bỏ qua kế hoạch có lời/lỗ dưới 2 (lãi tới mục tiêu phải gấp ít nhất 2 lần khoảng cắt lỗ).")
    if lo and hi and setup_fails:
        bad("Phiên mua chưa đạt kịch bản mua đẹp", "Theo nến ngày mua: " + "; ".join(setup_fails) + ".",
            "Mua lúc 14h15–14h29 khi mọi điều kiện của bảng Kiểm tra trước khi mua đều ✓.")
    stop_pct = (px - stop0) / px * 100 if px else 0
    if stop_pct > WIDE_STOP:
        bad("Cắt lỗ quá xa", f"Khoảng cắt lỗ {num(stop_pct, 1)}% (mua {_p(px)}, cắt lỗ {_p(stop0)}).",
            "Khoảng cắt lỗ trên 8% thường là mua xa điểm vào: chờ điểm gần hỗ trợ hơn, hoặc giảm khối lượng.")
    if settings and p.get("qty") and px > stop0 and light != "red":      # đèn đỏ: đã có mục riêng (không mở lệnh)
        cap = settings["capital"] * 1e6
        risk_pct = p["qty"] * (px - stop0) * 1000 / cap * 100 if cap else 0
        allow = settings["risk_pct"] * LIGHT_FACTOR.get(light or "", 1.0)
        if risk_pct > max(allow, 0.05) * 1.5:
            bad("Khối lượng quá lớn so với mức rủi ro",
                f"Nếu chạm cắt lỗ sẽ mất {num(risk_pct, 2)}% vốn, trong khi mức cho phép là {num(allow, 2)}%"
                + (f" (đèn {LIGHT_VN.get(light, light)})" if light in LIGHT_VN else "") + ".",
                "Tính khối lượng bằng máy tính trên trang mã: số cp = vốn × % rủi ro ÷ (giá mua − cắt lỗ).")
    n_bad = sum(1 for x in out if not x["ok"])
    if not n_bad:
        good("Lúc mua đúng kỷ luật", "Có điểm mua, đúng vùng, lời/lỗ đạt, đèn không đỏ.")
    # ---- lúc bán
    t1 = (p.get("targets") or [None])[0]
    stop_exit = next((e for e in rule["exits"] if e["why"] in STOP_KINDS), None)
    first_rule = rule["exits"][0] if rule["exits"] else None
    before = len(out)
    if stop_exit and stop_exit["d"] in days:
        i = days.index(stop_exit["d"])
        sold_d = next((s["d"] for s in sales if s["d"] >= stop_exit["d"]), None)
        late = (days.index(sold_d) - i) if sold_d in days else (len(days) - 1 - i)
        if late > LATE and (not sales or sales[0]["d"] >= stop_exit["d"]):
            why = "hết 20 phiên chưa tới T1" if stop_exit["why"] == "Hết thời gian" else f"đóng cửa dưới cắt lỗ ({stop_exit['why'].lower()})"
            bad("Giữ quá hạn 20 phiên" if stop_exit["why"] == "Hết thời gian" else "Cắt lỗ trễ",
                f"Luật báo bán ngày {_day(stop_exit['d'])} ({why}); "
                + (f"bạn bán ngày {_day(sold_d)}, trễ {late} phiên." if sold_d else f"đến nay vẫn chưa bán ({late} phiên)."),
                "Phiên đóng cửa dưới cắt lỗ (hoặc đủ 20 phiên chưa tới T1) thì bán ngay phiên sau, không chờ hồi.")
    if sales and (first_rule is None or sales[0]["d"] < first_rule["d"]) and (t1 is None or sales[0]["px"] < t1):
        cur = f"cắt lỗ {_p(p['stop'])}" + (f", T1 {_p(t1)}" if t1 else "")
        cmp = ""
        if r_real is not None and r_rule is not None:
            cmp = (f" Kết quả của bạn {num(r_real, 2)}R; nếu theo luật {num(r_rule, 2)}R"
                   + (" (luật vẫn đang giữ lệnh)" if not rule["exits"] or rule["open"] else "") + ".")
            if r_real > r_rule:
                cmp += " Lần này bán sớm có lợi, nhưng về lâu dài làm theo luật mới giữ được lợi thế."
        bad("Bán sớm khi chưa có tín hiệu bán",
            f"Bán ngày {_day(sales[0]['d'])} giá {_p(sales[0]['px'])} khi giá chưa chạm {cur}." + cmp,
            "Chỉ bán khi: đóng cửa dưới cắt lỗ, chạm mục tiêu, có phiên bán mạnh (KL ≥ 2 lần TB20 đóng cửa thấp) hoặc hết 20 phiên. "
            "Ghi lý do bán vào ghi chú để xem lại.")
    if p.get("status") == "closed" and len(out) == before:
        good("Bán đúng luật", "Bán theo tín hiệu của luật (cắt lỗ / mục tiêu / hết thời gian).")
    return out


def build(positions, sales_by_pos, bars_of, plan_at, backtest_avg_r=None, settings=None):
    """positions: các dòng bảng positions (đã parse targets); sales_by_pos: {pos_id: [sale tăng dần theo ngày]};
    bars_of(sym, from_d) -> OHLCV từ ngày mua; plan_at(sym, d) -> (plan, light) hoặc (plan, light, lý do chưa đạt
    kịch bản mua đẹp) tại ngày mua; settings: vốn / % rủi ro (core.risk) để xét khối lượng."""
    items = []
    for p in positions:
        bars = bars_of(p["sym"], p["entry_d"])
        if not bars:
            continue
        stop0 = p.get("stop0") or p["stop"]
        days = [b["d"] for b in bars]
        sales = sales_by_pos.get(p["id"], [])
        qty = p.get("qty")
        last_c = bars[-1]["c"]
        if qty:
            fills = [((s["qty"] or 0) / qty, s["px"]) for s in sales]
        elif sales:                                              # không ghi KL: một lần bán = bán hết
            fills = [(1.0, sales[-1]["px"])]
        else:
            fills = []
        left = max(0.0, 1 - sum(f for f, _ in fills))
        rule = simulate(p["entry_px"], stop0, p["targets"], bars, TIME_STOP)
        rule_fills = [(e["frac"], e["px"]) for e in rule["exits"]]
        got = plan_at(p["sym"], p["entry_d"])
        plan, light = got[0], got[1]
        setup_fails = got[2] if len(got) > 2 else []
        r_real = _r(p["entry_px"], stop0, fills, left, last_c)
        r_rule = _r(p["entry_px"], stop0, rule_fills, rule["left"], last_c)
        items.append(dict(
            id=p["id"], sym=p["sym"], kind=p.get("kind"), entry_d=p["entry_d"], entry_px=p["entry_px"], stop0=stop0,
            qty=qty, status=p["status"], last_sale=sales[-1]["d"] if sales else None,
            r_real=r_real, r_rule=r_rule,
            diff=None if r_real is None or r_rule is None else round(r_real - r_rule, 2),
            rule_done=not rule["open"], flags=entry_flags(p, plan, light) + exit_flags(p, sales, rule, days),
            lessons=lessons(p, plan, light, setup_fails, sales, rule, days, settings, r_real, r_rule, last_c)))
    closed = [x for x in items if x["status"] == "closed" and x["r_real"] is not None]
    n = len(closed)
    flagged = [x for x in closed if x["flags"]]
    summary = dict(
        n=n, open=sum(1 for x in items if x["status"] == "open"),
        win=round(100 * sum(1 for x in closed if x["r_real"] > 0) / n, 1) if n else None,
        avg_real=round(sum(x["r_real"] for x in closed) / n, 2) if n else None,
        avg_rule=round(sum(x["r_rule"] for x in closed if x["r_rule"] is not None) / n, 2) if n else None,
        backtest_avg_r=backtest_avg_r,
        n_flagged=len(flagged),
        r_lost=round(sum(min(0, x["diff"]) for x in closed if x["diff"] is not None and x["flags"]), 2),
        flag_counts={k: sum(1 for x in items if k in x["flags"]) for k in sorted({f for x in items for f in x["flags"]})})
    return dict(items=sorted(items, key=lambda x: x["entry_d"], reverse=True), summary=summary)


def sales_by_position(conn):
    """{pos_id: [dict(d, px, qty)] tăng dần}; lệnh đóng trước khi có bảng sales coi như một lần bán hết."""
    out = {}
    for r in conn.execute("SELECT pos_id, d, px, qty FROM sales ORDER BY d, id"):
        out.setdefault(r["pos_id"], []).append(dict(d=r["d"], px=r["px"], qty=r["qty"]))
    for r in conn.execute("SELECT id, exit_d, exit_px, qty FROM positions p WHERE status='closed' "
                          "AND NOT EXISTS (SELECT 1 FROM sales WHERE pos_id=p.id)"):
        out[r["id"]] = [dict(d=r["exit_d"], px=r["exit_px"], qty=r["qty"])]
    return out


def all_positions(conn):
    return [dict(r, targets=json.loads(r["targets"] or "[]"))
            for r in conn.execute("SELECT * FROM positions ORDER BY entry_d DESC, id DESC")]
