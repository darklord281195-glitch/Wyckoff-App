"""Kiểm tra logic Wyckoff trên dữ liệu cố định (chốt phiên 20/11/2026).
Kỳ vọng lấy từ các phân tích đã xác nhận bằng tay với skill /wyckoff."""
import json
from pathlib import Path
import pytest
from app.core.wyckoff import analyse
from app.core import signals as sig
from app.fmt import num, price

FX = Path(__file__).parent / "fixtures"
load = lambda s: json.load(open(FX / f"{s}.json"))
IDX = load("VNINDEX")


def ev(r, k):
    return [e for e in r["events"] if e["k"] == k]


def test_dig_sc_and_spring():
    r = analyse(load("DIG"), IDX)
    assert r["range"]["sc_d"] == "2026-07-28" and r["range"]["sup"] == pytest.approx(8.82, abs=0.01)
    sp = ev(r, "Spring")
    assert sp and sp[0]["d"] == "2026-10-06" and sp[0]["price"] == pytest.approx(8.71, abs=0.01)


def test_cii_range_and_spring():
    r = analyse(load("CII"), IDX)
    assert r["range"]["sup"] == pytest.approx(12.15, abs=0.01)
    assert r["range"]["res"] == pytest.approx(15.20, abs=0.01)
    assert any(e["price"] == pytest.approx(11.35, abs=0.01) for e in ev(r, "Spring"))


def test_tch_d_sos():
    r = analyse(load("TCH"), IDX)
    assert r["tag"] == "D-SOS"
    assert r["sos"]["d"] == "2026-11-04"
    assert r["range"]["res"] == pytest.approx(12.59, abs=0.01)


def test_cts_d_som_with_spring():
    r = analyse(load("CTS"), IDX)
    assert r["tag"] == "D sớm"
    assert r["levels"]["support"] == pytest.approx(18.80, abs=0.01)   # đáy Spring 14/10


def test_dpg_d_lps_signal():
    r = analyse(load("DPG"), IDX)
    assert r["tag"] == "D-LPS"
    kinds = [s["kind"] for s in sig.build("DPG", r, None, False)]
    assert "LPS" in kinds


def test_below_support_is_not_bc():
    r = analyse(IDX)                                   # VNINDEX 1.688,79 dưới đáy vùng 1.775,72
    assert r["tag"] == "dưới hỗ trợ" and r["stage"] == "below"
    assert r["plan"]["kind"] == "Không vào" and r["plan"]["entry_lo"] is None


def test_lps_signal_needs_hold():
    r = analyse(load("DPG"), IDX)
    assert r["lps_age"] >= 2                           # đáy LPS 18/11 đã giữ 2 phiên -> có tín hiệu (test trên)
    r["lps_age"] = 0                                   # đáy LPS là phiên hôm nay: giá còn đang giảm
    assert "LPS" not in [s["kind"] for s in sig.build("DPG", r, None, False)]


def test_traffic_light_takes_most_cautious():
    from app.core.market import traffic_light
    from app.config import VNI_RED, VNI_GREEN
    assert traffic_light(dict(c=1688.79, ma50=1748.05, ma200=1784.16), 33)["light"] == "red"    # phiên 20/11/2026
    up = dict(c=VNI_GREEN + 100, ma50=VNI_GREEN + 50, ma200=VNI_GREEN)
    assert traffic_light(up, 60)["light"] == "green"
    assert traffic_light(up, 40)["light"] == "yellow"                    # độ rộng yếu kéo xuống vàng
    low = dict(c=VNI_RED - 1, ma50=VNI_RED - 50, ma200=VNI_RED - 100)   # xu hướng tăng nhưng dưới ngưỡng đỏ .env
    assert traffic_light(low, 60)["light"] == "red"
    assert traffic_light(low, 60, fixed=False)["light"] == "green"


def test_rs_present():
    r = analyse(load("TCH"), IDX)
    assert r["rs5"] is not None and r["rs20"] is not None


def test_vn_format():
    assert num(1688.79, 2) == "1.688,79"
    assert price(12.65) == "12.650"


def _bars(closes, vols=None, hi=None):
    """Nến giả: o=c trước, h/l ±1% (hi ghi đè giá cao), KL mặc định 1."""
    out = []
    for i, c in enumerate(closes):
        h = (hi or {}).get(i, c * 1.01)
        out.append(dict(d=f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" if i < 336 else f"2027-{1 + (i-336) // 28:02d}-{1 + (i-336) % 28:02d}",
                        o=c, h=h, l=c * 0.99, c=c, v=(vols or {}).get(i, 1.0)))
    return out


def test_distribution_utad_then_sow():
    from app.core.wyckoff import distribution
    up = [10 + 10 * i / 99 for i in range(100)]                      # tăng 10 -> 20 (BC ở cuối)
    rng = [18.5 + (i % 6) * 0.2 for i in range(40)]                  # đi ngang 18,5–19,5, đáy AR ~18,3
    closes = up + rng + [19.6, 19.4] + [18.8] * 10
    utad = len(up) + len(rng)                                        # vượt đỉnh 20,2 rồi đóng 19,6 < đỉnh
    d = distribution(_bars(closes, hi={utad: 20.6}))
    assert d and d["tag"] == "UTAD" and [e["k"] for e in d["events"]].count("UTAD") == 1
    sow = len(closes)
    closes += [17.0]                                                 # thủng đáy AR, KL x3
    d = distribution(_bars(closes, vols={sow: 3.0}, hi={utad: 20.6}))
    assert d["tag"] == "SOW" and d["events"][-1]["k"] == "SOW"
    assert distribution(_bars(up + [x + 3 for x in rng])) is None    # vượt đỉnh đi tiếp: không phải phân phối


def test_utad_alert_only_for_watchlist_and_today():
    r = analyse(load("DPG"), IDX)
    r["distrib"] = dict(top=40, events=[dict(k="UTAD", d=r["d"])])
    assert "UTAD" in [x["kind"] for x in sig.build("DPG", r, None, True)]
    assert "UTAD" not in [x["kind"] for x in sig.build("DPG", r, None, False)]
    r["distrib"]["events"][0]["d"] = "2020-01-01"
    assert "UTAD" not in [x["kind"] for x in sig.build("DPG", r, None, True)]


def test_classify_variant_and_phase():
    from app.core.wyckoff import classify
    s = analyse(load("DPG"), IDX)["schema"]
    assert s["phase"] == "D" and s["variant"] in ("acc1", "acc2")
    assert analyse(load("VNINDEX"))["schema"]["title"].startswith("Đang thủng hỗ trợ")
    base = dict(tag="B/C", events=[dict(k="SC"), dict(k="AR"), dict(k="ST")], distrib=None)
    assert classify(base)["variant"] == "acc" and classify(base)["phase"] == "B"          # Pha B: chưa rõ mẫu
    base["events"].append(dict(k="Spring"))
    assert classify(base)["variant"] == "acc1" and classify(base)["phase"] == "C"
    d = dict(base, distrib=dict(tag="SOW", events=[dict(k="BC"), dict(k="AR"), dict(k="SOW")]))
    assert (classify(d)["variant"], classify(d)["phase"]) == ("dist2", "D")


def test_classify_reacc_redist():
    from app.core.wyckoff import classify
    ev = [dict(k="SC", vx=1), dict(k="AR", vx=1), dict(k="ST", vx=1)]
    assert classify(dict(tag="B/C", events=ev, weak_drop=True, drop=12))["variant"] == "reacc"
    br = dict(tag="dưới hỗ trợ", events=ev + [dict(k="Spring", vx=2.0)], ma50=10, ma200=12)
    assert (classify(br)["variant"], classify(br)["phase"]) == ("redist", "D")
    br["events"][-1]["vx"] = 0.8                        # KL thấp: vẫn có thể là Spring
    assert classify(br)["variant"] == "acc1"


def test_lower_highs():
    from app.core.wyckoff import lower_highs
    # AR ở 0 (h=20), rồi các nhịp hồi 19 → 18 → 17, giá đang ở đáy
    hs = [20, 16, 15, 16, 19, 16, 15, 14, 15, 18, 15, 14, 13, 14, 17, 14, 13, 12, 12]
    R = [dict(h=h, l=h - 1, c=h - 0.5) for h in hs]
    ch = lower_highs(R, 0, w=2)
    assert [hs[i] for i in ch] == [20, 19, 18, 17]
    R[-1]["c"] = 17.5            # đóng vượt đỉnh hạ gần nhất: chuỗi bị phá
    assert lower_highs(R, 0, w=2) == []
