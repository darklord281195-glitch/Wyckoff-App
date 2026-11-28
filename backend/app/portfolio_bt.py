"""Backtest cấp danh mục: vốn giới hạn, nhiều lệnh cùng lúc, đường vốn theo ngày; so với mua-giữ VNINDEX
và chiến lược chỉ theo đèn. Trả lời câu hỏi: dùng app có tốt hơn không làm gì không.

Lệnh lấy từ backtest.collect() (đã có phí + trượt giá trong `ret`). Xấp xỉ: các lần bán từng phần của một lệnh
được gộp thành một lần ở ngày thoát cuối; giữa chừng định giá theo giá đóng cửa.

Thêm các cách chia vốn (vì app chỉ có vị thế ~30% thời gian):
- Lõi–vệ tinh: một phần vốn cố định giữ chỉ số (mua-giữ VNINDEX, hoặc VNINDEX theo đèn), phần còn lại theo app;
  tái cân bằng về tỷ trọng mục tiêu ở phiên đầu mỗi tháng.
- App + tiền nhàn rỗi vào chỉ số: tiền mặt chưa dùng cho lệnh nào thì giữ VNINDEX khi đèn không đỏ.
VNINDEX là chỉ số giá (không gồm cổ tức ~1–2%/năm); quỹ ETF thật còn có phí quản lý và sai số bám chỉ số.

Chạy: .venv\\Scripts\\python -m app.backtest --portfolio"""
import json
import math
from collections import defaultdict

from .core import signals as sig
from .core.risk import LIGHT_FACTOR

START_CAPITAL = 100.0                  # triệu đồng (chỉ để hiển thị; mọi chỉ số tính theo tỷ lệ)
SWITCH_COST = 0.0025                   # chi phí mỗi lần mua/bán chỉ số (đổi theo đèn, tái cân bằng, rút/nộp tiền)
CORE_WEIGHTS = (0.5, 0.7, 0.8)         # lõi–vệ tinh: tỷ trọng phần chỉ số
NAMES = dict(app="Wyckoff app", vni="Mua-giữ VNINDEX", light="Chỉ theo đèn",
             app_idle="App + tiền nhàn rỗi vào chỉ số",
             **{f"cs_vni_{round(w * 100)}": f"Lõi VNINDEX {round(w * 100)}% + app {round((1 - w) * 100)}%" for w in CORE_WEIGHTS},
             **{f"cs_light_{round(w * 100)}": f"Lõi theo đèn {round(w * 100)}% + app {round((1 - w) * 100)}%" for w in CORE_WEIGHTS})
VARIANTS = ["app_idle"] + [f"cs_{c}_{round(w * 100)}" for c in ("vni", "light") for w in CORE_WEIGHTS]


def simulate(trades, dates, closes, risk_pct=1.0, max_pos=6, max_heat=6.0, idle=None):
    """Đường vốn của danh mục theo lệnh backtest.
    trades: dict có sym, entry_d, exit_d, entry, stop, ret (%), ready, kind, light.
    dates: các ngày giao dịch (tăng dần); closes: {mã: {ngày: giá đóng cửa}}.
    idle=(idx_c, light): tiền mặt nhàn rỗi giữ VNINDEX khi đèn phiên trước không đỏ; tốn SWITCH_COST khi đổi theo đèn,
    khi rút tiền từ chỉ số để vào lệnh và khi nộp tiền bán lệnh vào lại chỉ số.
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
    last_px, in_idx = {}, False
    for k, d in enumerate(dates):
        if idle and k:                         # tiền nhàn rỗi: hưởng VNINDEX hôm nay, rồi theo đèn đóng cửa phiên trước
            idx_c, light = idle
            if in_idx:
                cash *= idx_c[d] / idx_c[dates[k - 1]]
            want = light.get(dates[k - 1], "?") != "red"
            if want != in_idx:
                cash *= 1 - SWITCH_COST
                in_idx = want
        cost = SWITCH_COST if in_idx else 0.0  # phí rút/nộp tiền giữa chỉ số và lệnh
        # 1) thoát lệnh tới ngày thoát (lệnh chưa đóng ở cuối dữ liệu giữ nguyên tới hết)
        keep = []
        for h in held:
            if h["t"]["exit_d"] <= d and not h["t"]["open"]:
                cash += h["alloc"] * (1 + h["t"]["ret"] / 100) * (1 - cost)
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
            alloc = min(risk / ((t["entry"] - t["stop"]) / t["entry"]), cash / (1 + cost))
            if alloc < eq * 0.01:                               # quá nhỏ (hết tiền mặt): bỏ
                continue
            cash -= alloc * (1 + cost)
            held.append(dict(t=t, alloc=alloc, risk=risk))
            taken.append(t)
        value = sum(mark(h) for h in held)
        equity.append(cash + value)
        invested.append((value + (cash if in_idx else 0)) / (cash + value) if cash + value > 0 else 0)
    return equity, invested, taken


def blend(dates, core_eq, core_inv, sat_eq, sat_inv, w, cost=SWITCH_COST):
    """Lõi–vệ tinh: tỷ trọng w theo đường core, 1−w theo đường sat (cả hai bắt đầu từ 1), để tự trôi trong tháng;
    phiên đầu mỗi tháng tái cân bằng về w / 1−w, tốn `cost` trên phần tiền chuyển. Trả (equity, % có vị thế)."""
    c, s, eq, inv = w, 1.0 - w, [1.0], [w * core_inv[0] + (1 - w) * sat_inv[0]]
    for i in range(1, len(dates)):
        c *= core_eq[i] / core_eq[i - 1]
        s *= sat_eq[i] / sat_eq[i - 1]
        if dates[i][:7] != dates[i - 1][:7]:
            tot = c + s
            tot -= abs(c - w * tot) * cost
            c, s = w * tot, (1 - w) * tot
        eq.append(c + s)
        inv.append((c * core_inv[i] + s * sat_inv[i]) / (c + s))
    return eq, inv


def rank_variants(res):
    """Các cách chia vốn xếp theo mức hơn/kém mua-giữ VNINDEX ở giai đoạn TỆ hơn trong hai giai đoạn (lợi nhuận năm).
    Trả list dict(k, worst, both, mdd_better): both = thắng mua-giữ cả 2019–23 lẫn 2024–26."""
    out = []
    for k in VARIANTS + ["app", "light"]:
        if not all(k in res.get(p, {}) for p in ("2019–23", "2024–26", "Toàn kỳ")):
            continue
        ex = [res[p][k]["cagr"] - res[p]["vni"]["cagr"] for p in ("2019–23", "2024–26")]
        out.append(dict(k=k, worst=round(min(ex), 1), both=min(ex) > 0,
                        mdd_better=res["Toàn kỳ"][k]["mdd"] > res["Toàn kỳ"]["vni"]["mdd"]))
    return sorted(out, key=lambda x: -x["worst"])


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
    idle_eq, idle_inv, _ = simulate(trades, dates, closes, risk_pct, max_pos, max_heat, idle=(idx_c, light))
    vni_eq = [idx_c[d] / idx_c[dates[0]] for d in dates]
    lt_eq, lt_inv = light_strategy(dates, idx_c, light)
    curves = dict(app=(app_eq, app_inv), vni=(vni_eq, None), light=(lt_eq, lt_inv), app_idle=(idle_eq, idle_inv))
    for core, (ce, ci) in (("vni", (vni_eq, [1.0] * len(dates))), ("light", (lt_eq, lt_inv))):
        for w in CORE_WEIGHTS:
            curves[f"cs_{core}_{round(w * 100)}"] = blend(dates, ce, ci, app_eq, app_inv, w)
    res = {}
    for pname, a, b in PERIODS:
        ix = [i for i, d in enumerate(dates) if a <= d <= b]
        if len(ix) < 2:
            continue
        ds = [dates[i] for i in ix]
        res[pname] = {k: metrics(ds, [e[i] for i in ix], [v[i] for i in ix] if v else None) for k, (e, v) in curves.items()}
        res[pname]["app"]["trades"] = sum(1 for t in taken if a <= t["entry_d"] <= b)
    weekly = list(range(0, len(dates), 5)) + ([len(dates) - 1] if (len(dates) - 1) % 5 else [])   # ~1 điểm/tuần
    ranking = rank_variants(res)
    best = next((x["k"] for x in ranking if x["k"] in VARIANTS), None)
    slips = [t["slip"] for t in taken if t.get("slip") is not None]
    out = dict(params=dict(risk_pct=risk_pct, max_pos=max_pos, max_heat=max_heat, start=dates[0], end=dates[-1],
                           trades_total=len(trades), trades_taken=len(taken), names=NAMES, ranking=ranking, best=best,
                           slip=round(sum(slips) / len(slips), 2) if slips else None, switch_cost=SWITCH_COST * 100),
               metrics=res,
               curves=[dict(d=dates[i], **{k: round(e[i] * START_CAPITAL, 2) for k, (e, _) in curves.items()})
                       for i in weekly])
    conn.execute("INSERT INTO backtest_runs(created, params, metrics, curves) VALUES (datetime('now','localtime'),?,?,?)",
                 (json.dumps(out["params"]), json.dumps(res, ensure_ascii=False), json.dumps(out["curves"])))
    conn.commit()
    return out


def print_report(out):
    p = out["params"]
    print(f"\nBacktest danh mục {p['start']} → {p['end']}: rủi ro {p['risk_pct']}%/lệnh, tối đa {p['max_pos']} lệnh, "
          f"tổng rủi ro ≤ {p['max_heat']}%; vào {p['trades_taken']}/{p['trades_total']} lệnh (còn lại: bị ẩn theo đèn, hết chỗ, hết tiền).")
    keys = ["app", "vni", "light"] + VARIANTS
    for pname, m in out["metrics"].items():
        print(f"\n{pname:<10}{'':<34}{'tổng %':>8}{'năm %':>8}{'sụt max %':>11}{'Sharpe':>8}{'có vị thế %':>13}")
        for k in keys:
            x = m[k]
            sh = "–" if x.get("sharpe") is None else f"{x['sharpe']:.2f}"
            print(f"{'':<10}{NAMES[k]:<34}{x['total']:>8.1f}{x['cagr']:>8.1f}{x['mdd']:>11.1f}{sh:>8}{x['exposure']:>13}")
    yrs = out["metrics"]["Toàn kỳ"]
    print("\nTheo năm (%):" + " " * 23 + "  ".join(f"{y}" for y in yrs["app"]["yearly"]))
    for k in keys:
        print(f"  {NAMES[k]:<34}" + "  ".join(f"{v:>+5.1f}" for v in yrs[k]["yearly"].values()))
    print("\nSo với mua-giữ VNINDEX (lợi nhuận năm, giai đoạn tệ hơn trong 2019–23 / 2024–26):")
    for x in p["ranking"]:
        print(f"  {NAMES[x['k']]:<34}{x['worst']:>+6.1f} điểm %/năm"
              + (" · thắng cả hai giai đoạn" if x["both"] else "")
              + (" · sụt giảm nhỏ hơn" if x["mdd_better"] else ""))
