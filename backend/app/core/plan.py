"""Kế hoạch giao dịch theo Wyckoff cho một mã: phát hiện sớm (điểm sẵn sàng), vùng giá vào,
cắt lỗ (cấu trúc + thời gian), mục tiêu theo Nhân – Quả (đếm Point & Figure) và tỷ lệ lời/lỗ.

Hàm thuần: nhận R (OHLCV), kết quả analyse() và chỉ số các mốc trong R.
Đây là ước lượng của bộ lọc tự động, không phải khuyến nghị đầu tư.
"""
import math
from ..fmt import price, num

REVERSAL = 3          # P&F 3 ô đảo chiều (chuẩn Wyckoff)
TIME_STOP = 20        # số phiên chờ tối đa sau khi vào mà giá chưa chạm T1
LPS_HOLD = 2          # số phiên giá phải giữ trên đáy LPS thì LPS mới coi là xác nhận
TRAIL = 10            # sau T1: dời cắt lỗ lên đáy thấp nhất 10 phiên gần nhất


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


# ---------------------------------------------------------------- bước giá
def tick(p: float, floor: str) -> float:
    """Bước giá (nghìn đồng). HOSE: dưới 10.000đ là 10đ, dưới 50.000đ là 50đ, còn lại 100đ.
    HNX/UPCoM/không rõ sàn: 100đ (bội số 100đ hợp lệ ở mọi sàn)."""
    if floor == "HOSE":
        return 0.01 if p < 10 else 0.05 if p < 50 else 0.1
    return 0.1


def on_tick(p, floor, up=False):
    """Làm tròn p xuống (mặc định) hoặc lên theo bước giá của sàn; floor=None thì giữ nguyên."""
    if p is None or not floor:
        return p
    t = tick(p, floor)
    k = round(p / t, 6)                     # khử sai số float, vd 30.7/0.05 = 613.9999…
    return round((math.ceil(k) if up else math.floor(k)) * t, 2)


# ---------------------------------------------------------------- Point & Figure
def box_size(p: float) -> float:
    """Ô P&F theo mức giá (giá nghìn đồng; chỉ số dùng ô 10 điểm)."""
    for lim, box in ((5, 0.05), (10, 0.1), (20, 0.2), (50, 0.5), (100, 1.0), (300, 2.0)):
        if p < lim:
            return box
    return 10.0


def pnf_columns(closes: list[float], box: float, rev: int = REVERSAL) -> int:
    """Số cột P&F (giá đóng cửa, đảo chiều rev ô) hình thành trên chuỗi giá."""
    if len(closes) < 2:
        return 0
    q = lambda x: int(x // box)
    cur = q(closes[0]); direction = 0; cols = 1
    hi = lo = cur
    for x in closes[1:]:
        b = q(x)
        if direction >= 0 and b > hi:
            hi = b; direction = 1 if direction == 0 else direction
        elif direction <= 0 and b < lo:
            lo = b; direction = -1 if direction == 0 else direction
        if direction == 1 and b <= hi - rev:
            cols += 1; direction = -1; lo = b; hi = b
        elif direction == -1 and b >= lo + rev:
            cols += 1; direction = 1; hi = b; lo = b
        elif direction == 0:
            hi, lo = max(hi, b), min(lo, b)
    return cols


def cause_effect(R, i0: int, i1: int, base_low: float, count_line: float) -> dict:
    """Đếm ngang P&F từ i0 tới i1 (vùng tích lũy) -> mục tiêu thận trọng (từ đáy) và mở rộng (từ đường đếm)."""
    box = box_size(count_line)
    cols = pnf_columns([r["c"] for r in R[i0:i1 + 1]], box)
    width = cols * box * REVERSAL
    return dict(cols=cols, box=box, width=width,
                conservative=round(base_low + width, 3), aggressive=round(count_line + width, 3))


# ---------------------------------------------------------------- kháng cự phía trên
def overhead(R, above: float, end: int, win: int = 7) -> float | None:
    """Đỉnh swing gần nhất (theo giá) phía trên `above` trong ~1 năm trước `end` - vùng kẹt hàng đầu tiên."""
    cands = []
    for i in range(max(win, end - 250), end - win):
        h = R[i]["h"]
        if h > above and h == max(r["h"] for r in R[i - win:i + win + 1]):
            cands.append(h)
    return min(cands) if cands else None


# ---------------------------------------------------------------- điểm sẵn sàng
def readiness(R, r: dict, ix: dict) -> dict:
    """Chấm 0–100 mức 'sẵn sàng tăng' của một vùng tích lũy (phát hiện sớm, trước SOS)."""
    V = [x["v"] for x in R]; n = len(R)
    rg = r.get("range")
    if not rg:
        return dict(score=0, parts={})
    sup, res, sc = rg["sup"], rg["res"], ix["sc"]
    parts = {}
    # 1. Cung cạn: KL 10 phiên gần nhất so với KL quanh SC
    sc_v = _mean(V[max(0, sc - 2):sc + 3]) or 1e-9
    dry = _mean(V[-10:]) / sc_v
    parts["Cung cạn"] = 20 if dry <= 0.5 else 12 if dry <= 0.7 else 5 if dry <= 1.0 else 0
    # 2. Đáy nâng dần sau AR (đáy 20 phiên gần nhất > đáy 20 phiên trước đó, cả hai trên/sát SC)
    lo_a = min(x["l"] for x in R[-20:]); lo_b = min(x["l"] for x in R[-40:-20])
    spring_ok = any(e["k"] == "Spring" and (e["vx"] or 9) < 1.0 for e in r["events"])
    parts["Đáy nâng / Spring"] = (12 if lo_a > lo_b and lo_a >= sup * 0.98 else 0) + (8 if spring_ok else 0)
    # 3. Vị trí trong vùng
    posr = (r["c"] - sup) / max(res - sup, 1e-9)
    parts["Vị trí trong vùng"] = 20 if posr >= 0.75 else 10 if posr >= 0.5 else 0
    # 4. Sức mạnh tương đối so với VNINDEX
    parts["RS"] = (10 if (r.get("rs20") or -1) > 0 else 0) + (10 if (r.get("rs60") or -1) > 0 else 0)
    # 5. Độ dài 'Nhân' (số phiên từ SC)
    length = n - 1 - sc
    parts["Độ dài Nhân"] = 20 if length >= 40 else 10 if length >= 25 else 0
    return dict(score=min(100, sum(parts.values())), parts=parts, dry=round(dry, 2), pos=round(posr * 100))


# ---------------------------------------------------------------- kế hoạch
def make_plan(R, r: dict, ix: dict, floor: str | None = None) -> dict | None:
    rg = r.get("range")
    if not rg or r["stage"] in ("new",):
        return None
    n = len(R); c = r["c"]
    sup, res = rg["sup"], rg["res"]
    tag = r["tag"]; lv = r.get("levels") or {}
    low10 = min(x["l"] for x in R[-10:])
    plan = dict(kind=None, entry_lo=None, entry_hi=None, trigger="", stop=None, stop_reason="",
                time_stop=TIME_STOP, targets=[], rr=None, risk_pct=None, ready=readiness(R, r, ix), notes=[])

    recent_test = [e for e in r["events"] if e["k"] in ("Spring", "ST") and e["d"] >= R[max(0, n - 15)]["d"]]
    if tag in ("D-LPS", "D-LPS?"):
        # vùng LPS: từ đáy LPS (không thấp hơn trần cũ −6%) tới trần cũ +3%
        lo = max(min(lv.get("support", res), res * 0.97), res * 0.94); hi = res * 1.03
        plan.update(kind="LPS", entry_lo=lo, entry_hi=hi,
                    trigger=f"Vào khi giá giữ đáy LPS ít nhất {LPS_HOLD} phiên với KL thấp (dưới TB20), "
                            "ưu tiên phiên rút chân/đóng cửa nửa trên.",
                    stop=min(lv.get("invalid", res * 0.94), lv.get("support", res)) * 0.99,
                    stop_reason="Dưới đáy LPS / trần cũ −6%: LPS thất bại, cấu trúc Pha D hỏng")
    elif tag == "D-SOS":
        plan.update(kind="Backup", entry_lo=res, entry_hi=res * 1.03,
                    trigger="Không mua đuổi. Chờ giá lùi về test trần cũ với KL thấp rồi giữ được.",
                    stop=min(res * 0.95, low10) * 0.99,
                    stop_reason="Thủng trần cũ sâu: SOS là phá vỡ giả")
    elif tag == "D sớm" or (tag in ("sát trần", "B/C") and not recent_test):
        plan.update(kind="Phá trần (SOS)", entry_lo=res * 1.005, entry_hi=res * 1.04,
                    trigger=f"Vào khi đóng cửa vượt {price(res)} với KL ≥ 1,5 lần TB20; hoặc chờ LPS sau đó (an toàn hơn).",
                    stop=max(low10, res * 0.95) * 0.99,
                    stop_reason="Dưới đáy 10 phiên gần nhất: cú phá trần thất bại")
        if tag in ("sát trần", "B/C"):
            plan["notes"].append("Chưa có SOS: đây là kế hoạch chờ, chưa phải điểm vào.")
    elif tag in ("sát trần", "B/C") and recent_test:
        t = min(recent_test, key=lambda e: e["price"])
        plan.update(kind="Spring/Test", entry_lo=min(sup, t["price"]) * 1.005, entry_hi=max(sup, t["price"]) * 1.04,
                    trigger="Vào tỷ trọng nhỏ (≤1/3) sau phiên test đáy KL thấp và đóng cửa trên đáy SC.",
                    stop=min(t["price"], sup) * 0.98,
                    stop_reason="Thủng đáy Spring/Test: không phải tích lũy, giá giảm tiếp")
    elif tag == "dưới hỗ trợ":
        plan.update(kind="Không vào", trigger=f"Giá dưới hỗ trợ {price(sup)}: chờ phiên đóng cửa trở lại trên hỗ trợ "
                                             "với KL thấp (Spring) rồi mới tính.")
    elif tag == "E?":
        plan.update(kind="Đang tăng (Pha E)", trigger="Không mua đuổi; chờ nền tái tích lũy mới rồi tìm LPS.",
                    stop=max(res, low10 * 0.99), stop_reason="Người đang cầm: dời cắt lỗ theo đáy gần nhất / trần cũ")
    else:   # SOS hỏng
        plan.update(kind="Không vào", trigger="Cấu trúc hỏng, chờ vùng mới hình thành.",
                    stop=None, stop_reason="")

    # giá đặt lệnh phải đúng bước giá: vào từ entry_lo (lên) tới entry_hi (xuống), cắt lỗ và mục tiêu làm tròn xuống
    plan["entry_lo"] = on_tick(plan["entry_lo"], floor, up=True)
    plan["entry_hi"] = on_tick(plan["entry_hi"], floor)
    plan["stop"] = on_tick(plan["stop"], floor)

    # mục tiêu: kháng cự gần + Nhân–Quả (P&F)
    end = ix.get("lps") or ix.get("pk") or (n - 1)
    count_line = lv.get("support") if ix.get("lps") else res
    ce = cause_effect(R, ix["sc"], end, sup, count_line or res)
    ref = max(plan["entry_hi"] or c, c)
    above = ref * 1.02
    res_cands = [x for x in (overhead(R, above, n), lv.get("resistance")) if x and x > above]
    targets = []
    if res_cands:
        targets.append(dict(k="", price=min(res_cands), basis="Kháng cự gần (đỉnh cũ) – chốt lời một phần", ce=False))
    targets.append(dict(k="", price=ce["conservative"], ce=True,
                        basis=f"Nhân–Quả thận trọng: {ce['cols']} cột P&F × ô {num(ce['box'], 2)} × 3 cộng từ đáy"))
    targets.append(dict(k="", price=ce["aggressive"], ce=True, basis="Nhân–Quả mở rộng: cộng từ đường đếm"))
    targets = sorted([t for t in targets if t["price"] > above], key=lambda t: t["price"])
    for i, t in enumerate(targets):
        t["k"] = f"T{i + 1}"; t["price"] = on_tick(t["price"], floor)
    plan["targets"] = targets; plan["cause"] = ce
    plan["notes"].append(f"Đo đơn giản: trần + chiều cao vùng = {price(res + (res - sup))}.")

    if plan["entry_lo"] and plan["stop"]:
        entry = (plan["entry_lo"] + plan["entry_hi"]) / 2
        plan["risk_pct"] = round((plan["stop"] / entry - 1) * 100, 1)
        risk = max(entry - plan["stop"], 1e-9)
        if targets:
            for t in targets:
                t["pct"] = round((t["price"] / entry - 1) * 100, 1)
                t["rr"] = round((t["price"] - entry) / risk, 1)
            plan["rr_t1"] = targets[0]["rr"]
            main = next((t for t in targets if t["ce"]), targets[0])     # mục tiêu Nhân–Quả gần nhất
            plan["rr"] = main["rr"]; plan["main_target"] = main["k"]
        if plan["risk_pct"] < -8:
            plan["notes"].append("Cắt lỗ xa hơn 8%: giảm tỷ trọng hoặc chờ điểm vào gần hơn.")
        if plan["rr"] is not None and plan["rr"] < 2:
            plan["notes"].append("Lời/lỗ tới mục tiêu Nhân–Quả dưới 2 lần: chưa hấp dẫn.")
        plan["in_zone"] = plan["entry_lo"] <= c <= plan["entry_hi"]
    plan["exit"] = ("Chạm T1: bán 1/3 và dời cắt lỗ về giá vốn. Chạm T2: bán thêm 1/3. "
                    f"Phần còn lại dời cắt lỗ lên đáy thấp nhất {TRAIL} phiên, bán hết ở mục tiêu cuối. "
                    f"Sau {TIME_STOP} phiên chưa chạm T1: thoát (Nhân chưa đủ). "
                    "Thấy cung (KL lớn mà đóng cửa gần đáy phiên / upthrust) thì siết cắt lỗ.")
    for k in ("entry_lo", "entry_hi", "stop"):
        if plan[k] is not None: plan[k] = round(plan[k], 3)
    return plan


def supply_sign(R) -> bool:
    """Dấu hiệu cung phiên cuối: KL ≥ 2 lần TB20 nhưng giá đóng ở 40% dưới của biên độ phiên."""
    V = [x["v"] for x in R]; x = R[-1]
    rng = x["h"] - x["l"]
    return rng > 0 and V[-1] >= 2 * _mean(V[-21:-1]) and (x["c"] - x["l"]) / rng <= 0.4
