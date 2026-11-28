"""Backtest danh mục: giới hạn số lệnh, rủi ro, tiền mặt; đường vốn và sụt giảm; chiến lược theo đèn."""
from app import portfolio_bt as P

DATES = [f"2026-01-{d:02d}" for d in range(1, 21)]


def trade(sym, entry_d, exit_d, ret, ready=70, light="green", kind="LPS", entry=10.0, stop=9.0):
    return dict(sym=sym, entry_d=entry_d, exit_d=exit_d, ret=ret, ready=ready, light=light, kind=kind,
                entry=entry, stop=stop, open=False)


def flat(sym):
    return {sym: {d: 10.0 for d in DATES}}


def test_sizing_and_exit_return():
    # rủi ro 1% vốn, cắt lỗ cách 10% -> phân bổ 10% vốn; lệnh lãi 20% -> vốn +2%
    eq, inv, taken = P.simulate([trade("A", DATES[1], DATES[5], 20.0)], DATES, flat("A"))
    assert len(taken) == 1 and abs(eq[-1] - 1.02) < 1e-9 and abs(inv[2] - 0.1) < 1e-9 and inv[-1] == 0


def test_limits_hidden_and_priority():
    ts = [trade(f"S{i}", DATES[1], DATES[9], 0.0, ready=50 + i) for i in range(8)]       # 8 ứng viên cùng ngày
    ts.append(trade("R", DATES[1], DATES[9], 50.0, light="red"))                         # đèn đỏ: bị ẩn
    closes = {t["sym"]: {d: 10.0 for d in DATES} for t in ts}
    _, _, taken = P.simulate(ts, DATES, closes, max_pos=6)
    assert len(taken) == 6 and "R" not in {t["sym"] for t in taken}
    assert {t["sym"] for t in taken} == {f"S{i}" for i in range(2, 8)}                   # ưu tiên điểm cao
    _, _, taken = P.simulate(ts, DATES, closes, max_pos=6, max_heat=2.5)                 # tổng rủi ro ≤ 2,5%
    assert len(taken) == 2
    _, _, taken = P.simulate([trade("Y", DATES[1], DATES[9], 0, light="yellow", kind="SOS mới")], DATES, flat("Y"))
    assert len(taken) == 1                                                               # vàng: SOS mới vẫn được


def test_metrics_and_light_strategy():
    m = P.metrics(DATES[:4], [1.0, 1.1, 0.88, 0.99])
    assert m["total"] == -1.0 and m["mdd"] == -20.0
    idx = {d: 100.0 + i for i, d in enumerate(DATES)}
    light = {d: ("red" if i < 10 else "green") for i, d in enumerate(DATES)}
    eq, inv = P.light_strategy(DATES, idx, light)
    assert eq[5] == 1.0 and inv[5] == 0 and inv[-1] == 1.0 and eq[-1] > 1.0              # đèn đỏ: đứng ngoài


def test_blend_rebalances_monthly():
    dates = ["2026-01-30", "2026-01-31", "2026-02-02", "2026-02-03"]
    core, sat = [1.0, 1.1, 1.1, 1.1], [1.0, 1.0, 1.0, 1.0]
    eq, inv = P.blend(dates, core, [1.0] * 4, sat, [0.0] * 4, 0.5, cost=0)
    assert abs(eq[1] - 1.05) < 1e-12                       # trong tháng: tự trôi (0,5 × 1,1 + 0,5)
    assert abs(eq[-1] - 1.05) < 1e-12 and abs(inv[2] - 0.5) < 1e-12   # đầu tháng 2: về lại 50/50
    eq2, _ = P.blend(dates, core, [1.0] * 4, sat, [0.0] * 4, 0.5, cost=0.01)
    assert eq2[-1] < eq[-1]                                # tái cân bằng tốn phí


def test_idle_cash_follows_index_unless_red():
    idx = {d: 100.0 * (1.01 ** i) for i, d in enumerate(DATES)}         # chỉ số tăng 1%/phiên
    red = {d: "red" for d in DATES}
    green = {d: "green" for d in DATES}
    base, _, _ = P.simulate([], DATES, {})
    assert base[-1] == 1.0                                               # không lệnh, không tiền nhàn rỗi: đứng yên
    eq_red, _, _ = P.simulate([], DATES, {}, idle=(idx, red))
    assert eq_red[-1] == 1.0                                             # đèn đỏ: giữ tiền mặt
    eq_g, inv_g, _ = P.simulate([], DATES, {}, idle=(idx, green))
    assert abs(eq_g[-1] - (1 - P.SWITCH_COST) * 1.01 ** 18) < 1e-9 and inv_g[-1] == 1.0   # vào chỉ số từ phiên 2
    t = [trade("A", DATES[5], DATES[9], 10.0)]
    eq_t, _, taken = P.simulate(t, DATES, flat("A"), idle=(idx, green))
    # lệnh lãi 10% trong 4 phiên chỉ số +4%: hơn tiền nhàn rỗi một chút, sau phí rút/nộp tiền
    assert len(taken) == 1 and eq_g[-1] < eq_t[-1] < eq_g[-1] + 0.01


def test_rank_variants_by_worst_period():
    m = lambda c, mdd=-10: dict(cagr=c, mdd=mdd)
    res = {p: dict(vni=m(5, -30), app=m(a), light=m(4), app_idle=m(i), **{k: m(0) for k in P.VARIANTS if k != "app_idle"})
           for p, a, i in (("2019–23", 9, 7), ("2024–26", -4, 6), ("Toàn kỳ", 2, 6.5))}
    r = P.rank_variants(res)
    assert r[0]["k"] == "app_idle" and r[0]["both"] and r[0]["mdd_better"] and r[0]["worst"] == 1
    assert next(x for x in r if x["k"] == "app")["worst"] == -9
