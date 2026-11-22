"""Phân tích Wyckoff (tích lũy) cho một mã - port từ skill wyckoff (find_range + analyse của screen.py),
bổ sung danh sách sự kiện, mốc giá và sức mạnh tương đối (RS) so với VNINDEX.

Đầu vào: R = list dict {d,o,h,l,c,v} tăng dần theo ngày (giá nghìn đồng, KL triệu cp).
Hàm thuần, không gọi mạng/DB.
"""
import datetime as dt
from ..fmt import num, price, day
from .plan import make_plan, supply_sign

ANALYSIS_DAYS = 420          # cùng cửa sổ dữ liệu với skill (fetch 420 ngày)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _ratio(a, b):
    return round(a / b, 2) if b else None


def trim(R, days=ANALYSIS_DAYS, today=None):
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    return [r for r in R if r["d"] >= since]


def find_range(R, lookback=190):
    """(sc, ar, mlo_i): vùng đáy GẦN NHẤT sau đỉnh lớn gần nhất.
    SC = đáy cục bộ sớm nhất trong dải 8% trên đáy thấp nhất (đáy thấp nhất có thể là Spring về sau)."""
    n = len(R); S = max(0, n - lookback)
    pk = max(range(S, max(S + 1, n - 20)), key=lambda i: R[i]["h"])
    if n - 5 - pk >= 25: S = pk
    mlo_i = min(range(S, n), key=lambda i: R[i]["l"]); mlo = R[mlo_i]["l"]
    loc = [i for i in range(S, n - 5) if R[i]["l"] <= mlo * 1.08
           and R[i]["l"] == min(r["l"] for r in R[max(S, i-5):i+6])] or [mlo_i]
    sc = loc[0]
    ar_end = min(n, sc + 45)
    ar = max(range(sc + 1, ar_end), key=lambda i: R[i]["h"]) if ar_end > sc + 1 else None
    return sc, ar, mlo_i


def _ret(R, k):
    return R[-1]["c"] / R[-1 - k]["c"] - 1 if len(R) > k else None


def rs_vs_index(R, IDX):
    """Chênh lệch % thay đổi giá mã so với VNINDEX trong 5/20/60 phiên (theo ngày khớp)."""
    if not IDX: return {}
    idx_by_d = {r["d"]: r for r in IDX}
    common = [r for r in R if r["d"] in idx_by_d]
    I = [idx_by_d[r["d"]] for r in common]
    out = {}
    for k in (5, 20, 60):
        a, b = _ret(common, k), _ret(I, k)
        out[f"rs{k}"] = None if a is None or b is None else round((a - b) * 100, 1)
    return out


def distribution(R, lookback=190):
    """Vùng phân phối gần nhất (ngược với tích lũy) hoặc None.
    BC = đỉnh cao nhất sau đợt tăng ≥ 30%; AR = đáy nhịp giảm sau BC; sau đó dò ST/UTAD quanh đỉnh,
    SOW = đóng cửa thủng đáy AR với KL ≥ 1,5×TB20, LPSY = nhịp hồi sau SOW không vượt lại đáy AR, KL thấp hơn."""
    n = len(R); S = max(0, n - lookback)
    if n - S < 60:
        return None
    V = [r["v"] for r in R]
    avg = lambda i: _mean(V[max(0, i - 20):i])
    # BC = đỉnh cục bộ SỚM NHẤT trong dải 5% dưới đỉnh cao nhất (đỉnh cao nhất có thể là UTAD về sau)
    mx = max(R[i]["h"] for i in range(S, n - 10))
    bc = next((i for i in range(S, n - 10) if R[i]["h"] >= mx * 0.95
               and R[i]["h"] == max(r["h"] for r in R[max(S, i - 5):i + 6])),
              max(range(S, n - 10), key=lambda i: R[i]["h"]))
    if R[bc]["h"] < 1.3 * min(r["l"] for r in R[max(0, bc - 250):bc + 1]):
        return None                                         # trước BC không có đợt tăng đáng kể
    if bc + 3 >= min(n, bc + 30):
        return None
    ar = min(range(bc + 3, min(n, bc + 30)), key=lambda i: R[i]["l"])
    top, bot = R[bc]["h"], R[ar]["l"]
    if bot > top * 0.93 or any(R[i]["c"] > top * 1.02 for i in range(ar, n)):
        return None                                         # vùng quá hẹp, hoặc đã vượt đỉnh đi tiếp (tăng tiếp)
    ev = lambda i, k, pos: dict(d=R[i]["d"], k=k, pos=pos, price=R[i]["l"] if pos == "low" else R[i]["h"],
                                v=round(V[i], 2), vx=_ratio(V[i], avg(i)))
    events = [ev(bc, "BC", "high"), ev(ar, "AR", "low")]
    sow = next((i for i in range(ar + 3, n) if R[i]["c"] < bot and V[i] >= 1.5 * avg(i)), None)
    k, end = ar + 1, sow if sow is not None else n
    while k < end:                                          # các lần quay lại gần đỉnh: ST, vượt đỉnh rồi đóng dưới = UTAD
        if R[k]["h"] >= top * 0.97:
            j = k
            while j + 1 < end and R[j + 1]["h"] >= top * 0.97: j += 1
            b = max(range(k, j + 1), key=lambda i: R[i]["h"])
            events.append(ev(b, "UTAD" if R[b]["h"] > top and R[b]["c"] < top else "ST", "high"))
            k = j + 1
        else:
            k += 1
    lpsy = None
    if sow is not None:
        events.append(ev(sow, "SOW", "low"))
        if sow + 2 < n:
            j = max(range(sow + 1, n), key=lambda i: R[i]["h"])
            if j > sow and R[j]["h"] <= bot * 1.03 and _mean(V[sow + 1:j + 1]) < V[sow] and R[-1]["c"] < R[j]["h"]:
                lpsy = j; events.append(ev(j, "LPSY", "high"))
    c = R[-1]["c"]
    tag = ("LPSY" if lpsy is not None else "Markdown" if sow is not None and c < bot * 0.9 else
           "SOW" if sow is not None else "UTAD" if any(e["k"] == "UTAD" for e in events) else "Pha B?")
    events.sort(key=lambda e: e["d"])
    return dict(tag=tag, top=top, bot=bot, start=R[bc]["d"], events=events)


NAMES = {"acc1": "Tích lũy mẫu 1 (có Spring)", "acc2": "Tích lũy mẫu 2 (không Spring, đáy nâng)",
         "dist1": "Phân phối mẫu 1 (có UTAD)", "dist2": "Phân phối mẫu 2 (không UTAD, đỉnh hạ)",
         "reacc": "Tái tích lũy (nghỉ giữa xu hướng tăng)", "redist": "Tái phân phối (nghỉ giữa xu hướng giảm)"}
ACC_NOTE = {"A": "Pha A: vừa dừng giảm, chưa có ST. Chưa mua.",
            "B": "Pha B: đang tích lũy. Chờ Spring hoặc đáy nâng, rồi SOS vượt trần.",
            "C": "Pha C: vừa có Spring. Chỉ thăm dò nhỏ, chờ Test giữ đáy và SOS.",
            "D": "Pha D: đã có sức mạnh. Vùng mua LPS/Backup theo kế hoạch.",
            "E": "Pha E: đã tăng xa vùng. Không mua đuổi, chờ nền mới."}


def classify(r):
    """Mã đang giống biến thể sơ đồ nào: dict(variant acc1/acc2/dist1/dist2/None, phase A–E/None, title, note)."""
    dd = r.get("distrib")
    if dd and dd["tag"] != "Pha B?":
        v = "dist1" if any(e["k"] == "UTAD" for e in dd["events"]) else "dist2"
        ph = {"UTAD": "C", "SOW": "D", "LPSY": "D", "Markdown": "E"}[dd["tag"]]
        note = {"C": "Pha C: vừa vượt đỉnh rồi rơi lại (UTAD). Không mua phá đỉnh; đang giữ thì siết cắt lỗ.",
                "D": "Pha D: đã thủng đáy vùng (SOW), cung áp đảo. Không bắt đáy.",
                "E": "Pha E: đang giảm giá (Markdown). Đứng ngoài, chờ vùng tích lũy mới."}[ph]
        return dict(variant=v, phase=ph, title=NAMES[v], note=note)
    tag = r["tag"]
    if tag == "mới tạo đáy":
        return dict(variant=None, phase="A", title="Vừa tạo đáy mới", note="Chưa thành vùng: chờ AR rồi ST.")
    ks = [e["k"] for e in r["events"]]
    v = "acc1" if "Spring" in ks else "acc2"
    if tag == "SOS hỏng":
        return dict(variant=v, phase=None, title=NAMES[v] + " – thất bại",
                    note="Đã vượt trần rồi rơi sâu lại vào vùng: cấu trúc hỏng, có thể chuyển thành phân phối.")
    down = r.get("ma200") and r["ma50"] < r["ma200"]
    brk = next((e for e in reversed(r["events"]) if e["k"] == "Spring"), None)
    if tag == "dưới hỗ trợ" and down and brk and (brk["vx"] or 0) >= 1.5:
        # thủng đáy với KL lớn trong xu hướng giảm: SOW của vùng tái phân phối, không phải Spring
        return dict(variant="redist", phase="D", title=NAMES["redist"],
                    note="Pha D: thủng đáy vùng với KL lớn (≥ 1,5 lần TB20) khi MA50 < MA200: cung áp đảo, "
                         "xu hướng giảm đang tiếp diễn. Không bắt đáy, chờ vùng tích lũy mới.")
    if tag == "dưới hỗ trợ":
        return dict(variant="acc1", phase="C", title="Đang thủng hỗ trợ: Spring hoặc gãy thật",
                    note="Thành Spring (mẫu 1) nếu đóng cửa lại trên đáy SC với KL thấp; KL lớn mà không lấy lại "
                         "được đáy là gãy thật, giá có thể giảm tiếp.")
    ph = ("D" if tag.startswith("D") else "E" if tag == "E?" else "C" if "Spring" in ks
          else "B" if "ST" in ks else "A")
    note = ACC_NOTE[ph]
    if r.get("weak_drop"):   # vùng sau nhịp giảm < 20%: nghỉ giữa xu hướng tăng
        return dict(variant="reacc", phase=ph, title=NAMES["reacc"],
                    note=f"Vùng đi ngang sau nhịp điều chỉnh nông ({r.get('drop')}% từ đỉnh). {note} "
                         "App chưa báo mua với tái tích lũy (chưa kiểm chứng bằng backtest).")
    if ph in ("A", "B"):     # Pha C chưa tới: chưa biết có Spring (mẫu 1) hay đáy nâng (mẫu 2)
        v, title = "acc", "Tích lũy – chưa rõ mẫu 1 hay 2 (Pha C sẽ quyết định)"
    else:
        title = NAMES[v]
    if dd:   # vùng đi ngang ngay sau đợt tăng ≥ 30%: đọc theo tích lũy hay phân phối đều được
        note += " Lưu ý: vùng này nằm ngay sau một đợt tăng mạnh (BC), cũng có thể là phân phối; SOS hay SOW sẽ cho biết."
    return dict(variant=v, phase=ph, title=title, note=note)


def analyse(R, IDX=None, floor=None, lookback=190, keep_distrib=False):
    """Trả dict kết quả. R phải là dữ liệu đã cắt ~420 ngày (dùng trim()).
    floor = sàn niêm yết (HOSE/HNX/UPCOM) để làm tròn giá kế hoạch theo bước giá; None = không làm tròn.
    lookback = số phiên cuối được dò vùng tích lũy/phân phối (trang mã cho người dùng tự chọn khoảng).
    keep_distrib = giữ vùng phân phối dù sau đó đã có vùng tích lũy mới (người dùng tự chọn khoảng để xem cả hai)."""
    n = len(R)
    if n < 120:
        return None
    V = [r["v"] for r in R]
    c = R[-1]["c"]
    avg20 = _mean(V[-20:])
    base = dict(
        d=R[-1]["d"], c=c, chg=round((c / R[-2]["c"] - 1) * 100, 2), v=round(V[-1], 2),
        vx=_ratio(V[-1], _mean(V[-21:-1])),
        ma20=round(_mean([r["c"] for r in R[-20:]]), 3), ma50=round(_mean([r["c"] for r in R[-50:]]), 3),
        ma200=round(_mean([r["c"] for r in R[-200:]]), 3) if n >= 200 else None,
        avg20=round(avg20, 3), liq=round(avg20 * c, 1),             # tỷ đồng/ngày
        lo52=min(r["l"] for r in R[-250:]), hi52=max(r["h"] for r in R[-250:]),
    )
    base["pos52"] = round((c - base["lo52"]) / max(base["hi52"] - base["lo52"], 1e-9) * 100)
    base.update(rs_vs_index(R, IDX))
    base["distrib"] = distribution(R, lookback)

    sc, ar, mlo_i = find_range(R, lookback)
    if ar is None or ar <= sc + 2:
        out = dict(base, tag="mới tạo đáy", stage="new", events=[], range=None, levels={})
        out["schema"] = classify(out)
        return out

    dd = base["distrib"]
    if dd and dd["events"][-1]["d"] < R[sc]["d"] and not keep_distrib:
        base["distrib"] = None           # phân phối đã xong, giá đã tạo vùng tích lũy mới sau đó
    hi_before = max(r["h"] for r in R[max(0, sc-250):sc+1])
    drop = 1 - R[sc]["l"] / hi_before
    res, sup = R[ar]["h"], R[sc]["l"]
    ev = lambda i, k, pos: dict(d=R[i]["d"], k=k, pos=pos, price=R[i]["l"] if pos == "low" else R[i]["h"],
                                v=round(V[i], 2), vx=_ratio(V[i], _mean(V[max(0, i-20):i])))
    events = [ev(sc, "SC", "low"), ev(ar, "AR", "high")]

    # các lần quay về gần đáy sau AR: ST / Spring
    k = ar + 1
    while k < n:
        if R[k]["l"] <= sup * 1.04:
            j = k
            while j + 1 < n and R[j + 1]["l"] <= sup * 1.04: j += 1
            b = min(range(k, j + 1), key=lambda i: R[i]["l"])
            events.append(ev(b, "Spring" if R[b]["l"] < sup else "ST", "low"))
            k = j + 1
        else:
            k += 1

    sos = None
    for i in range(ar + 5, n):
        if R[i]["c"] > res and V[i] >= 1.5 * _mean(V[i-20:i]):
            sos = i; break
    dist = c / res - 1
    extra = ""; pk = None; lps = None; t = None
    levels = dict(support=sup, resistance=res, invalid=sup)
    if sos is not None:
        events.append(ev(sos, "SOS", "high"))
        pk = max(range(sos, n), key=lambda i: R[i]["h"])
        up_v = _mean(V[sos:pk + 1]); pb_v = _mean(V[pk + 1:])
        if dist > 0.25:
            tag = "E?"
        elif dist < -0.06:
            tag = "SOS hỏng"
        elif pk >= n - 3 and c >= R[pk]["h"] * 0.97:
            tag = "D-SOS"
        elif pb_v < up_v * 0.8:
            tag = "D-LPS"
        else:
            tag = "D-LPS?"; extra = "KL lùi lớn"
        if pk > sos:
            events.append(ev(pk, "Đỉnh sau SOS", "high"))
        if tag.startswith("D-LPS") and pk < n - 1:
            lps = min(range(pk + 1, n), key=lambda i: R[i]["l"])
            events.append(ev(lps, "LPS?" if tag == "D-LPS?" else "LPS", "low"))
            extra = f"lùi {num((c / R[pk]['h'] - 1) * 100)}% từ đỉnh {price(R[pk]['h'])}" + (f", {extra}" if extra else "")
            levels = dict(support=R[lps]["l"], resistance=R[pk]["h"], invalid=round(min(res * 0.94, R[lps]["l"]), 3))
        elif tag == "D-SOS":
            levels = dict(support=res, resistance=R[pk]["h"], invalid=round(res * 0.94, 3))
    else:
        t = min(range(ar + 1, n), key=lambda i: R[i]["l"]) if ar + 1 < n else None
        tag = "dưới hỗ trợ" if c < sup else "sát trần" if dist >= -0.06 else "B/C"
        if t is not None and t < n - 5:
            ups = [V[i] for i in range(t + 1, n) if R[i]["c"] > R[i-1]["c"]]
            dns = [V[i] for i in range(t + 1, n) if R[i]["c"] < R[i-1]["c"]]
            rise = c / R[t]["l"] - 1
            if dist >= -0.06 and rise >= 0.12 and _mean(ups) > _mean(dns) * 1.2:
                tag = "D sớm"
                extra = (f"bật +{num(rise * 100)}% từ đáy {price(R[t]['l'])} ngày {day(R[t]['d'])}"
                         f"{' (Spring)' if R[t]['l'] < sup else ''}")
                levels = dict(support=R[t]["l"], resistance=res, invalid=min(R[t]["l"], sup))
    weak_drop = drop < 0.20
    stage = ("D" if tag.startswith("D") else "near" if tag == "sát trần" else "below" if tag == "dưới hỗ trợ" else
             "E" if tag == "E?" else "failed" if tag == "SOS hỏng" else "BC")
    events.sort(key=lambda e: e["d"])
    out = dict(base, tag=tag, stage=stage, extra=extra, weak_drop=weak_drop, drop=round(drop * 100, 1),
               dist=round(dist * 100, 1), lps_age=None if lps is None else n - 1 - lps,
               range=dict(start=R[sc]["d"], sup=sup, res=res, sc_d=R[sc]["d"], ar_d=R[ar]["d"]),
               sos=None if sos is None else dict(d=R[sos]["d"], v=round(V[sos], 2),
                                                 vx=_ratio(V[sos], _mean(V[sos-20:sos]))),
               events=events, levels=levels)
    out["plan"] = make_plan(R, out, dict(sc=sc, ar=ar, sos=sos, pk=pk, lps=lps, t=t), floor)
    out["supply"] = supply_sign(R)
    out["schema"] = classify(out)
    return out
