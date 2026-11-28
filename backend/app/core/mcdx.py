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
    key = state_of(b, b5, m, h, cl)
    label, tone, detail = STATES[key]
    return dict(banker=round(b / TOP * 100, 1), hot=round(max(h - b, 0) / TOP * 100, 1), retail=round((TOP - top) / TOP * 100, 1),
                banker_ma=round(m / TOP * 100, 1) if m is not None else None,
                banker_chg5=round((b - b5) / TOP * 100, 1) if b5 is not None else None,
                state=key, label=label, tone=tone, detail=detail)


# Nhãn trạng thái (đọc ghép với pha Wyckoff). tone: good / warn / bad / info. Thứ tự xét: trên xuống.
STATES = {
    "none": ("Chưa ai kéo", "bad", "Không có đỏ, vàng thấp: xu hướng dài hạn chưa tăng, dòng tiền đầu cơ cũng yếu. Đứng ngoài."),
    "spec": ("Chỉ có đầu cơ", "warn", "Có vàng (lướt sóng) nhưng chưa có đỏ: xu hướng dài hạn chưa tăng. Không mua theo, chờ cấu trúc."),
    "exit": ("Tay to rút ở vùng cao", "bad", "Đỏ co lại trong khi giá ở gần đỉnh 20 phiên: dấu hiệu phân phối. Siết cắt lỗ, không mua mới."),
    "enter": ("Tay to bắt đầu vào", "good", "Đỏ vừa xuất hiện / dâng dần: thường gặp lúc chuyển Pha C sang D. Theo dõi sát, chờ điểm mua của kế hoạch."),
    "lead": ("Tay to dẫn dắt", "good", "Đỏ trên nửa cột và còn tăng: đang trong nhịp tăng (Pha D/E). Chỉ mua ở nhịp lùi (LPS/Backup)."),
    "fade": ("Tay to giảm", "warn", "Đỏ đang co lại so với 5 phiên trước: đà tăng dài hạn yếu đi."),
    "hold": ("Tay to có mặt", "info", "Có đỏ, không tăng không giảm rõ."),
}
STEP = 2.0                     # thay đổi banker đáng kể trong 5 phiên (= 10% cột)


def state_of(b, b5, ma, h, cl) -> str:
    """Khóa trạng thái từ banker hiện tại b, 5 phiên trước b5, TB 10 phiên ma, hot h (0–20) và giá đóng cửa cl."""
    near_top = len(cl) >= 20 and cl[-1] >= 0.97 * max(cl[-20:])
    falling = b5 is not None and b5 - b >= STEP and (ma is None or b < ma)
    if b <= 0:
        return "spec" if h >= 4 else "none"
    if falling and near_top:
        return "exit"
    if b5 is not None and (b5 <= 0 or (b - b5 >= STEP and b < 10)):
        return "enter"
    if b >= 10 and (ma is None or b >= ma):
        return "lead"
    if falling:
        return "fade"
    return "hold"
