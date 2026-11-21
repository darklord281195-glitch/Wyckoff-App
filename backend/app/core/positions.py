"""Quản lý một lệnh đã mua theo kế hoạch Wyckoff: cắt lỗ, chốt lời từng phần, dời cắt lỗ, cắt theo thời gian.

Dùng chung cho cảnh báo danh mục hằng ngày (scan, api) và backtest, nên luật được đo chính là luật được cảnh báo.
Hàm thuần, không lưu trạng thái: mỗi lần gọi chạy lại từ phiên mua, nên lỡ vài ngày quét vẫn ra đúng.
"""
from ..fmt import price
from .plan import TIME_STOP, TRAIL

SETTLE = 2        # T+2: hàng về chiều phiên thứ 2 sau ngày mua -> sớm nhất bán ở phiên đó (giá đóng cửa)
PART = 1 / 3      # tỷ lệ bán ở mỗi mục tiêu; mục tiêu cuối bán hết phần còn lại


def simulate(entry_px: float, stop: float, targets: list[float], bars: list[dict], time_stop: int = TIME_STOP) -> dict:
    """bars[0] = phiên mua (đã khớp ở entry_px), các phiên sau tăng dần theo ngày.

    Luật: đóng cửa dưới cắt lỗ -> bán phiên sau · chạm T1 -> bán 1/3, dời cắt lỗ về giá vốn · chạm T2 -> bán 1/3 ·
    mục tiêu cuối -> bán hết · sau T1 dời cắt lỗ lên đáy thấp nhất TRAIL phiên · time_stop phiên chưa chạm T1 -> bán.
    Trả dict(stop, left, hit, next, pending, open, exits=[dict(d, px, frac, why)], events=[dict(d, kind, text)])."""
    targets = sorted(t for t in targets if t > entry_px)
    left, hit, pending = 1.0, 0, None
    exits, events = [], []
    ev = lambda b, kind, text: events.append(dict(d=b["d"], kind=kind, text=text))
    for i, b in enumerate(bars):
        can = i >= SETTLE
        if pending:                                        # lệnh bán đã báo từ phiên trước
            if can:
                exits.append(dict(d=b["d"], px=b["c"] if i == SETTLE else b["o"], frac=left, why=pending))
                left, pending = 0, None
                break
            continue
        # phiên T+2 chỉ bán được buổi chiều: dùng giá đóng cửa; sau đó chạm mục tiêu trong phiên là khớp
        while can and hit < len(targets) and (b["c"] if i == SETTLE else b["h"]) >= targets[hit]:
            last = hit == len(targets) - 1
            frac = left if last else min(PART, left)
            px = b["c"] if i == SETTLE else max(targets[hit], b["o"])      # mở cửa vượt mục tiêu: khớp giá mở cửa
            exits.append(dict(d=b["d"], px=px, frac=frac, why=f"T{hit + 1}"))
            left -= frac
            text = f"chạm T{hit + 1} {price(targets[hit])}: bán {'hết' if last else '1/3'}"
            if hit == 0 and not last and stop < entry_px:
                stop = entry_px
                text += f", dời cắt lỗ về giá vốn {price(entry_px)}"
            ev(b, "Chốt lời", text)
            hit += 1
        if left <= 1e-9:
            left = 0
            break
        if b["c"] < stop:
            pending = "Cắt lỗ" if hit == 0 else "Thủng cắt lỗ dời"
            ev(b, "Cắt lỗ", f"đóng cửa {price(b['c'])} dưới cắt lỗ {price(stop)}: bán "
                            + ("phiên tới" if i + 1 >= SETTLE else "khi hàng về (chiều T+2)"))
        elif hit == 0 and i >= time_stop:
            pending = "Hết thời gian"
            ev(b, "Hết thời gian", f"{time_stop} phiên chưa chạm T1"
                                   + (f" {price(targets[0])}" if targets else "") + ": bán phiên tới")
        elif hit:
            low = min(x["l"] for x in bars[max(0, i - TRAIL + 1):i + 1])
            if low > stop:
                stop = low
                ev(b, "Dời cắt lỗ", f"dời cắt lỗ lên {price(stop)} (đáy thấp nhất {TRAIL} phiên)")
    return dict(stop=stop, left=round(left, 4), hit=hit, next=targets[hit] if hit < len(targets) else None,
                pending=pending, open=left > 1e-9, exits=exits, events=events)
