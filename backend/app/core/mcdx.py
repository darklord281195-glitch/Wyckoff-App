"""MCDX Plus: chia "dòng tiền" thành 3 lớp theo RSI (Wilder, như TradingView), mỗi lớp 0–20 (20 = 100% cột).

- Banker (đỏ, "tay to"):      1,5 × (RSI 50 phiên − 50), kẹp trong 0–20
- Hot money (vàng, đầu cơ):   0,7 × (RSI 40 phiên − 30), kẹp trong 0–20
- Nhỏ lẻ (xanh):              phần còn lại của cột
- Đường TB Banker:            trung bình 10 phiên của Banker

Chỉ là RSI tách tầng: không đo được dòng tiền thật theo nhà đầu tư. Dùng để xem bối cảnh; có lọc được lệnh tốt hơn
hay không thì kiểm bằng `app.backtest --compare`.
"""

BANKER = (50, 50, 1.5)        # (chu kỳ RSI, mốc trừ, độ nhạy)
HOT = (40, 30, 0.7)
TOP = 20.0
MA = 10


def rsi_wilder(cl: list[float], n: int) -> list[float | None]:
    """RSI kiểu Wilder (RMA), None ở n nến đầu."""
    out: list[float | None] = [None] * len(cl)
    g = l = 0.0
    for i in range(1, len(cl)):
        d = cl[i] - cl[i - 1]
        up, dn = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            g += up / n; l += dn / n
        else:
            g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n
        if i >= n:
            out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def _layer(rsi, base, sens):
    return [None if x is None else min(TOP, max(0.0, sens * (x - base))) for x in rsi]


def series(cl: list[float]) -> dict:
    """Chuỗi banker / hot / banker_ma (0–20, None khi chưa đủ dữ liệu) cho cả dãy giá đóng cửa."""
    banker = _layer(rsi_wilder(cl, BANKER[0]), BANKER[1], BANKER[2])
    hot = _layer(rsi_wilder(cl, HOT[0]), HOT[1], HOT[2])
    ma: list[float | None] = [None] * len(cl)
    for i in range(len(cl)):
        w = banker[max(0, i - MA + 1):i + 1]
        if len(w) == MA and all(x is not None for x in w):
            ma[i] = sum(w) / MA
    return dict(banker=banker, hot=hot, banker_ma=ma)


def last(cl: list[float]) -> dict | None:
    """Giá trị phiên cuối theo %: banker, hot (phần vàng lộ ra trên đỏ), retail; banker_ma; xu hướng 5 phiên của banker."""
    s = series(cl)
    b, h, m = s["banker"][-1] if cl else None, s["hot"][-1] if cl else None, s["banker_ma"][-1] if cl else None
    if b is None or h is None:
        return None
    b5 = s["banker"][-6] if len(cl) >= 6 else None
    top = max(b, h)
    return dict(banker=round(b / TOP * 100, 1), hot=round(max(h - b, 0) / TOP * 100, 1), retail=round((TOP - top) / TOP * 100, 1),
                banker_ma=round(m / TOP * 100, 1) if m is not None else None,
                banker_chg5=round((b - b5) / TOP * 100, 1) if b5 is not None else None)
