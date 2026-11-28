"""Chỉ báo kỹ thuật, port đúng các hàm TS trong frontend/components/WyckoffChart.tsx (ema, indicators, ichimoku)
để điểm Top 10 khớp với biểu đồ người dùng đang xem."""
from .mcdx import rsi_wilder

ICHI_SHIFT = 26           # mây dời trước 26 nến (như ICHI_SHIFT ở frontend)
MACD_OK = 33              # 26 + 9 − 2 nến để MACD/tín hiệu ổn định


def ema(xs: list[float], n: int) -> list[float]:
    """EMA cùng độ dài, phần tử đầu = giá trị đầu."""
    a, out = 2 / (n + 1), []
    for i, x in enumerate(xs):
        out.append(out[i - 1] + a * (x - out[i - 1]) if i else x)
    return out


def rsi(cl: list[float], n: int = 14) -> list[float | None]:
    """RSI Wilder (None ở n nến đầu), cùng hàm với MCDX."""
    return rsi_wilder(cl, n)


def macd(cl: list[float]) -> dict:
    """MACD(12, 26, 9): dict(macd, signal, hist), None khi i < 33."""
    e12, e26 = ema(cl, 12), ema(cl, 26)
    m = [a - b for a, b in zip(e12, e26)]
    s = ema(m, 9)
    ok = lambda i: i >= MACD_OK
    return dict(macd=[x if ok(i) else None for i, x in enumerate(m)],
                signal=[x if ok(i) else None for i, x in enumerate(s)],
                hist=[m[i] - s[i] if ok(i) else None for i in range(len(m))])


def ichimoku(rows: list[dict]) -> dict:
    """tenkan (9), kijun (26), span_a / span_b dời trước 26 nến (độ dài n + 26), chikou."""
    n = len(rows)

    def mid(i, p):
        if i < p - 1:
            return None
        w = rows[i - p + 1:i + 1]
        return (max(r["h"] for r in w) + min(r["l"] for r in w)) / 2

    tenkan = [mid(i, 9) for i in range(n)]
    kijun = [mid(i, 26) for i in range(n)]
    span_a: list[float | None] = [None] * (n + ICHI_SHIFT)
    span_b: list[float | None] = [None] * (n + ICHI_SHIFT)
    for i in range(n):
        a, b = tenkan[i], kijun[i]
        span_a[i + ICHI_SHIFT] = (a + b) / 2 if a is not None and b is not None else None
        span_b[i + ICHI_SHIFT] = mid(i, 52)
    chikou = [rows[i + ICHI_SHIFT]["c"] if i + ICHI_SHIFT < n else None for i in range(n)]
    return dict(tenkan=tenkan, kijun=kijun, span_a=span_a, span_b=span_b, chikou=chikou)
