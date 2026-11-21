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
