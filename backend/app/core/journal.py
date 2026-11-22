"""Nhật ký giao dịch: so kết quả thật của người dùng với kết quả nếu làm đúng luật, và đánh dấu vi phạm kỷ luật.

R thật   = lãi/lỗ sau phí ÷ rủi ro ban đầu (giá mua − cắt lỗ lúc mua), gồm phần chưa bán tính theo giá hiện tại.
R luật   = cùng điểm mua, bán theo positions.simulate (cắt lỗ, chốt T1/T2, dời cắt lỗ, hết thời gian).
Giá trong DB là nghìn đồng."""
import json

from .positions import simulate
from .plan import TIME_STOP

BUY_FEE, SELL_FEE = 0.0015, 0.0025       # cùng mức với backtest (mua 0,15%; bán 0,15% + thuế 0,1%)
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


def build(positions, sales_by_pos, bars_of, plan_at, backtest_avg_r=None):
    """positions: các dòng bảng positions (đã parse targets); sales_by_pos: {pos_id: [sale tăng dần theo ngày]};
    bars_of(sym, from_d) -> OHLCV từ ngày mua; plan_at(sym, d) -> (plan, light) tại ngày mua."""
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
        plan, light = plan_at(p["sym"], p["entry_d"])
        r_real = _r(p["entry_px"], stop0, fills, left, last_c)
        r_rule = _r(p["entry_px"], stop0, rule_fills, rule["left"], last_c)
        items.append(dict(
            id=p["id"], sym=p["sym"], kind=p.get("kind"), entry_d=p["entry_d"], entry_px=p["entry_px"], stop0=stop0,
            qty=qty, status=p["status"], last_sale=sales[-1]["d"] if sales else None,
            r_real=r_real, r_rule=r_rule,
            diff=None if r_real is None or r_rule is None else round(r_real - r_rule, 2),
            rule_done=not rule["open"], flags=entry_flags(p, plan, light) + exit_flags(p, sales, rule, days)))
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
