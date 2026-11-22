"""Backtest cấp danh mục: vốn giới hạn, nhiều lệnh cùng lúc, đường vốn theo ngày; so với mua-giữ VNINDEX
và chiến lược chỉ theo đèn. Trả lời câu hỏi: dùng app có tốt hơn không làm gì không.

Lệnh lấy từ backtest.collect() (đã có phí + trượt giá trong `ret`). Xấp xỉ: các lần bán từng phần của một lệnh
được gộp thành một lần ở ngày thoát cuối; giữa chừng định giá theo giá đóng cửa.

Chạy: .venv\\Scripts\\python -m app.backtest --portfolio"""
import json
import math
from collections import defaultdict

from .core import signals as sig
from .core.risk import LIGHT_FACTOR

START_CAPITAL = 100.0                  # triệu đồng (chỉ để hiển thị; mọi chỉ số tính theo tỷ lệ)
SWITCH_COST = 0.0025                   # chiến lược theo đèn: chi phí mỗi lần mua/bán chỉ số


def simulate(trades, dates, closes, risk_pct=1.0, max_pos=6, max_heat=6.0):
    """Đường vốn của danh mục theo lệnh backtest.
    trades: dict có sym, entry_d, exit_d, entry, stop, ret (%), ready, kind, light.
    dates: các ngày giao dịch (tăng dần); closes: {mã: {ngày: giá đóng cửa}}.
    Trả (equity theo ngày, % vốn đang đầu tư theo ngày, danh sách lệnh đã vào)."""
    by_entry = defaultdict(list)
    for t in trades:
        if t["kind"] in sig.HIDE.get(t["light"], ()):           # luật ẩn theo đèn như app
            continue
        if t["entry"] <= t["stop"]:
            continue
        by_entry[t["entry_d"]].append(t)
    cash, held, taken = 1.0, [], []
    equity, invested = [], []
    last_px = {}
    for d in dates:
        # 1) thoát lệnh tới ngày thoát (lệnh chưa đóng ở cuối dữ liệu giữ nguyên tới hết)
        keep = []
        for h in held:
            if h["t"]["exit_d"] <= d and not h["t"]["open"]:
                cash += h["alloc"] * (1 + h["t"]["ret"] / 100)
            else:
                keep.append(h)
        held = keep
        # giá trị hiện tại để tính quy mô lệnh mới
        def mark(h):
            px = closes.get(h["t"]["sym"], {}).get(d) or last_px.get(h["t"]["sym"]) or h["t"]["entry"]
            last_px[h["t"]["sym"]] = px
            return h["alloc"] * px / h["t"]["entry"]
        eq = cash + sum(mark(h) for h in held)
        # 2) vào lệnh mới trong ngày: ưu tiên điểm sẵn sàng cao
        for t in sorted(by_entry.get(d, []), key=lambda t: -(t.get("ready") or 0)):
            if len(held) >= max_pos:
                break
            factor = LIGHT_FACTOR.get(t["light"], 1.0)
            risk = eq * risk_pct / 100 * factor
            heat = sum(h["risk"] for h in held)
            if risk <= 0 or heat + risk > eq * max_heat / 100 + 1e-12:     # +ε: 6 × 1% đúng bằng ngưỡng vẫn được
                continue
            alloc = min(risk / ((t["entry"] - t["stop"]) / t["entry"]), cash)
            if alloc < eq * 0.01:                               # quá nhỏ (hết tiền mặt): bỏ
                continue
            cash -= alloc
            held.append(dict(t=t, alloc=alloc, risk=risk))
            taken.append(t)
        value = sum(mark(h) for h in held)
        equity.append(cash + value)
        invested.append(value / (cash + value) if cash + value > 0 else 0)
    return equity, invested, taken


def light_strategy(dates, idx_c, light):
    """Giữ VNINDEX khi đèn phiên trước không đỏ, tiền mặt khi đỏ; tốn SWITCH_COST mỗi lần đổi."""
    eq, inv, holding, v = [], [], False, 1.0
    for i, d in enumerate(dates):
        if i:
            if holding:
                v *= idx_c[d] / idx_c[dates[i - 1]]
            want = light.get(dates[i - 1], "?") != "red"       # quyết định theo đèn đóng cửa phiên trước
            if want != holding:
                v *= 1 - SWITCH_COST
                holding = want
        eq.append(v); inv.append(1.0 if holding else 0.0)
    return eq, inv


def metrics(dates, eq, inv=None):
    """CAGR, sụt giảm lớn nhất, Sharpe (ngày, năm hóa 252), % thời gian có vị thế, lợi nhuận từng năm."""
    n = len(eq)
    if n < 2 or eq[0] <= 0:
        return {}
    years = n / 252
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1 if years > 0 else 0
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    r = [eq[i] / eq[i - 1] - 1 for i in range(1, n)]
    mu = sum(r) / len(r)
    sd = math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1)) if len(r) > 1 else 0
    by_year = {}
    for d, v in zip(dates, eq):
        by_year[d[:4]] = v                                # giá trị cuối mỗi năm
    prev, yearly = eq[0], {}
    for y in sorted(by_year):
        yearly[y] = round((by_year[y] / prev - 1) * 100, 1); prev = by_year[y]
    return dict(total=round((eq[-1] / eq[0] - 1) * 100, 1), cagr=round(cagr * 100, 1), mdd=round(mdd * 100, 1),
                sharpe=round(mu / sd * math.sqrt(252), 2) if sd else None,
                exposure=round(100 * sum(inv) / n) if inv else 100, yearly=yearly)


PERIODS = (("2019–23", "0000", "2023-12-31"), ("2024–26", "2024-01-01", "9999"), ("Toàn kỳ", "0000", "9999"))


def run(conn, trades, idx, light, risk_pct=1.0, max_pos=6, max_heat=6.0, log=print):
    """Chạy cả ba đường, tính chỉ số theo giai đoạn, lưu backtest_runs; trả dict kết quả."""
    from .core.data import get_ohlcv
    start = min(t["entry_d"] for t in trades)
    dates = [r["d"] for r in idx if r["d"] >= start]
    idx_c = {r["d"]: r["c"] for r in idx}
    closes = {s: {r["d"]: r["c"] for r in get_ohlcv(conn, s, 10000, refresh=False) if r["d"] >= start}
              for s in {t["sym"] for t in trades}}
    app_eq, app_inv, taken = simulate(trades, dates, closes, risk_pct, max_pos, max_heat)
    vni_eq = [idx_c[d] / idx_c[dates[0]] for d in dates]
    lt_eq, lt_inv = light_strategy(dates, idx_c, light)
    curves = dict(app=(app_eq, app_inv), vni=(vni_eq, None), light=(lt_eq, lt_inv))
    res = {}
    for pname, a, b in PERIODS:
        ix = [i for i, d in enumerate(dates) if a <= d <= b]
        if len(ix) < 2:
            continue
        ds = [dates[i] for i in ix]
        res[pname] = {k: metrics(ds, [e[i] for i in ix], [v[i] for i in ix] if v else None) for k, (e, v) in curves.items()}
        res[pname]["app"]["trades"] = sum(1 for t in taken if a <= t["entry_d"] <= b)
    weekly = list(range(0, len(dates), 5)) + ([len(dates) - 1] if (len(dates) - 1) % 5 else [])   # ~1 điểm/tuần
    out = dict(params=dict(risk_pct=risk_pct, max_pos=max_pos, max_heat=max_heat, start=dates[0], end=dates[-1],
                           trades_total=len(trades), trades_taken=len(taken)),
               metrics=res,
               curves=[dict(d=dates[i], app=round(app_eq[i] * START_CAPITAL, 2), vni=round(vni_eq[i] * START_CAPITAL, 2),
                            light=round(lt_eq[i] * START_CAPITAL, 2)) for i in weekly])
    conn.execute("INSERT INTO backtest_runs(created, params, metrics, curves) VALUES (datetime('now','localtime'),?,?,?)",
                 (json.dumps(out["params"]), json.dumps(res, ensure_ascii=False), json.dumps(out["curves"])))
    conn.commit()
    return out


def print_report(out):
    p = out["params"]
    print(f"\nBacktest danh mục {p['start']} → {p['end']}: rủi ro {p['risk_pct']}%/lệnh, tối đa {p['max_pos']} lệnh, "
          f"tổng rủi ro ≤ {p['max_heat']}%; vào {p['trades_taken']}/{p['trades_total']} lệnh (còn lại: bị ẩn theo đèn, hết chỗ, hết tiền).")
    names = dict(app="Wyckoff app", vni="Mua-giữ VNINDEX", light="Chỉ theo đèn")
    for pname, m in out["metrics"].items():
        print(f"\n{pname:<10}{'':<18}{'tổng %':>8}{'năm %':>8}{'sụt max %':>11}{'Sharpe':>8}{'có vị thế %':>13}")
        for k in ("app", "vni", "light"):
            x = m[k]
            sh = "–" if x.get("sharpe") is None else f"{x['sharpe']:.2f}"
            print(f"{'':<10}{names[k]:<18}{x['total']:>8.1f}{x['cagr']:>8.1f}{x['mdd']:>11.1f}{sh:>8}{x['exposure']:>13}")
    yrs = out["metrics"]["Toàn kỳ"]
    print("\nTheo năm (%):  " + "  ".join(f"{y}" for y in yrs["app"]["yearly"]))
    for k in ("app", "vni", "light"):
        print(f"  {names[k]:<16}" + "  ".join(f"{v:>+5.1f}" for v in yrs[k]["yearly"].values()))
