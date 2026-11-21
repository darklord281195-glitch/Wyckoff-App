from ..config import VNI_RED, VNI_GREEN
from ..fmt import num

ORDER = ("red", "yellow", "green")          # từ thận trọng nhất
ACTION = {"green": "Mua ở LPS với tỷ trọng bình thường", "yellow": "Chỉ mua ở LPS, tỷ trọng 1/3–1/2",
          "red": "Không mua mới, siết cắt lỗ"}


def traffic_light(idx_result: dict | None, breadth: float | None = None, fixed: bool = True) -> dict:
    """Đèn thị trường = màu thận trọng nhất trong:
    (1) xu hướng VNINDEX: đỏ nếu dưới MA200 và MA50 < MA200, xanh nếu trên MA50 và MA50 > MA200, còn lại vàng;
    (2) độ rộng (% mã thanh khoản trên MA50): đỏ < 30, vàng < 50, còn lại xanh;
    (3) ngưỡng cố định VNI_RED/VNI_GREEN trong .env (fixed=False bỏ qua, vd backtest nhiều năm)."""
    if not idx_result:
        return dict(light="?", text="Không có dữ liệu VNINDEX")
    c, m50, m200 = idx_result["c"], idx_result.get("ma50"), idx_result.get("ma200")
    lights, why = [], []
    if m50 and m200:
        if c < m200 and m50 < m200:
            lights.append("red"); why.append(f"dưới MA200 {num(m200)}, MA50 < MA200")
        elif c > m50 > m200:
            lights.append("green"); why.append(f"trên MA50 {num(m50)}, MA50 > MA200")
        else:
            lights.append("yellow"); why.append(f"{'trên' if c >= m50 else 'dưới'} MA50 {num(m50)}")
    if breadth is not None:
        lights.append("red" if breadth < 30 else "yellow" if breadth < 50 else "green")
        why.append(f"{num(breadth)}% mã thanh khoản trên MA50")
    if fixed:
        lights.append("green" if c >= VNI_GREEN else "red" if c < VNI_RED else "yellow")
        why.append(f"trên {num(VNI_GREEN)}" if c >= VNI_GREEN else f"dưới {num(VNI_RED)}" if c < VNI_RED
                   else f"giữa {num(VNI_RED)}–{num(VNI_GREEN)}")
    light = min(lights or ["yellow"], key=ORDER.index)
    return dict(light=light, text=f"{ACTION[light]} ({' · '.join(why)})", c=c, chg=idx_result.get("chg"),
                red=VNI_RED, green=VNI_GREEN, breadth=breadth)
