"""MCDX Plus: banker = 1,5 × (RSI50 − 50), hot = 0,7 × (RSI40 − 30), kẹp 0–20; % theo cột 20."""
from app.core import mcdx


def test_rsi_wilder_extremes():
    up = [10 + i for i in range(80)]
    assert mcdx.rsi_wilder(up, 14)[13] is None and mcdx.rsi_wilder(up, 14)[-1] == 100.0
    down = [100 - i for i in range(80)]
    assert mcdx.rsi_wilder(down, 14)[-1] == 0.0


def test_layers_rising_falling_sideways():
    up = mcdx.last([10 + i * 0.1 for i in range(200)])
    assert (up["banker"], up["hot"], up["retail"]) == (100.0, 0.0, 0.0)          # tăng liên tục: toàn đỏ
    down = mcdx.last([50 - i * 0.1 for i in range(200)])
    assert (down["banker"], down["hot"], down["retail"]) == (0.0, 0.0, 100.0)    # giảm liên tục: toàn xanh
    side = mcdx.last([10 + (i % 2) * 0.2 for i in range(300)])                    # đi ngang: RSI ~50
    assert side["banker"] < 5 and 60 < side["hot"] < 75 and abs(side["banker"] + side["hot"] + side["retail"] - 100) < 0.2
    assert mcdx.last([10.0] * 30) is None                                         # chưa đủ 50 phiên


def test_states():
    S = mcdx.state_of
    flat = [10.0] * 30
    assert S(0, 0, 0, 2, flat) == "none" and S(0, 0, 0, 8, flat) == "spec"
    assert S(3, 0, 1, 10, flat) == "enter"                       # đỏ vừa xuất hiện
    assert S(15, 14, 12, 18, flat) == "lead"                     # trên nửa cột, trên đường TB
    top = [10.0] * 19 + [11.0]                                    # giá ở đỉnh 20 phiên
    assert S(8, 14, 12, 15, top) == "exit" and S(8, 14, 12, 15, [11.0] * 19 + [9.0]) == "fade"
    assert S(6, 6, 6, 12, flat) == "hold"
    m = mcdx.last([10 + i * 0.1 for i in range(200)])
    assert m["state"] == "lead" and m["label"] == "Tay to dẫn dắt" and m["tone"] == "good"


def test_mcdx_advisory_does_not_block():
    from app import intraday as it
    import datetime as dt
    R = [dict(d=(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat(), o=10, h=10.1, l=9.9, c=10.0 - i * 0.01, v=1.0)
         for i in range(80)]                                        # giảm dần: banker 0%
    R.append(dict(d="2026-12-01", o=9.2, h=9.3, l=9.15, c=9.29, v=0.5))
    plan = dict(kind="LPS", entry_lo=9.1, entry_hi=9.4, stop=8.8, rr=3.0, targets=[dict(k="T1", price=10.5)], selloff=None)
    items = it.checklist(plan, R)
    adv = next(x for x in items if x["key"] == "mcdx")
    assert adv["ok"] is False and adv["advisory"] and it.good_setup(plan, R)[0]                 # không chặn tự mua
    assert it.verdict(items, "green", 9.29, plan)[0] == "buy"                                    # không chặn kết luận
