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
