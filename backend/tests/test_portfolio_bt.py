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
