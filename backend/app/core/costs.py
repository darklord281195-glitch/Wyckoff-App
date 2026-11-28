"""Chi phí giao dịch dùng chung cho backtest, chấm tín hiệu thật (forward) và sổ lệnh thử nghiệm (paper).

Trượt giá mỗi chiều = nửa bước giá / giá + phần theo thanh khoản:
- Nửa bước giá: giá trong dữ liệu là giá khớp, trung bình nằm giữa giá mua và giá bán tốt nhất; mua phải trả giá bán,
  bán phải nhận giá mua, nên mỗi chiều mất khoảng nửa chênh lệch (chênh lệch tối thiểu = 1 bước giá). Cả vòng mua + bán
  mất 1 bước. Mã giá thấp / sàn HNX, UPCoM (bước 100đ) chịu nhiều hơn: 100đ ở giá 12.000 là 0,83% mỗi vòng.
- Phần thanh khoản: mã giao dịch ít có chênh lệch rộng hơn 1 bước và sổ lệnh mỏng, đặt lệnh dễ đẩy giá.
"""
from .plan import tick

BUY_FEE, SELL_FEE = 0.0015, 0.0025      # phí môi giới 0,15% mỗi chiều; bán thêm thuế 0,1%
SLIP_FIXED = 0.0025                     # mức cố định cũ (0,25%/chiều), dùng khi chọn --slip 0.25 hoặc thiếu dữ liệu
LIQ_SLIP = ((50, 0.0005), (20, 0.0015), (10, 0.003))   # GT TB20 ≥ ngưỡng (tỷ đồng/ngày) -> phần trượt giá thêm
LOW_LIQ_SLIP = 0.005                    # GT TB20 dưới 10 tỷ


def slip_for(px: float, liq_bil: float | None, floor: str | None) -> float:
    """Trượt giá mỗi chiều (tỷ lệ, 0.003 = 0,3%) của một lệnh ở giá px (nghìn đồng), GT TB20 liq_bil (tỷ đồng/ngày).
    floor: HOSE / HNX / UPCOM; không rõ sàn thì tính bước 100đ (thận trọng)."""
    half_tick = tick(px, floor or "UPCOM") / 2 / px if px > 0 else 0.0
    extra = next((s for lim, s in LIQ_SLIP if (liq_bil or 0) >= lim), LOW_LIQ_SLIP)
    return round(half_tick + extra, 5)


def net_r(px: float, stop: float, gross: float, slip: float) -> tuple[float, float]:
    """(R, lãi %) sau phí + trượt giá. gross = tiền thu về mỗi cp trước phí (tổng frac × giá bán, phần còn lại theo giá cuối)."""
    value = gross * (1 - SELL_FEE - slip)
    cost = px * (1 + BUY_FEE + slip)
    return round((value - cost) / max(px - stop, px * 1e-3), 2), round((value / cost - 1) * 100, 2)
