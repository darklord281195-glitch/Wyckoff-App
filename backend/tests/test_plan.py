import json
from pathlib import Path
from app.core.wyckoff import analyse
from app.core.plan import pnf_columns, box_size, tick
from app.core import signals as sig

FX = Path(__file__).parent / "fixtures"
load = lambda s: json.load(open(FX / f"{s}.json"))
IDX = load("VNINDEX")


def test_pnf_columns_basic():
    # lên 5 ô, đảo xuống 3 ô, lên lại 3 ô -> 3 cột
    closes = [10, 11, 12, 13, 14, 15, 12, 11, 14, 15]
    assert pnf_columns(closes, 1.0) == 3
    assert pnf_columns([10, 10.5, 10.2], 1.0) == 1       # chưa đủ 3 ô đảo chiều
    assert box_size(12) == 0.2 and box_size(1688) == 10.0


def test_plan_levels_are_consistent():
    for s in ["TCH", "DPG", "CTS", "CII", "DIG"]:
        r = analyse(load(s), IDX); p = r["plan"]
        assert p and p["entry_lo"] < p["entry_hi"], s
        assert p["stop"] < p["entry_lo"], s                        # cắt lỗ dưới vùng vào
        prices = [t["price"] for t in p["targets"]]
        assert prices == sorted(prices) and all(x > max(p["entry_hi"], r["c"]) for x in prices), s


def test_dpg_lps_plan_contains_price_and_good_rr():
    r = analyse(load("DPG"), IDX); p = r["plan"]
    assert p["kind"] == "LPS" and p["entry_lo"] <= r["c"] <= p["entry_hi"]
    assert p["rr"] >= 2
    assert "cắt lỗ" in sig.plan_text(p)


def test_plan_prices_on_tick():
    on = lambda x, t: abs(x / t - round(x / t)) < 1e-6
    p = analyse(load("DPG"), IDX, "HOSE")["plan"]
    prices = [p["entry_lo"], p["entry_hi"], p["stop"]] + [t["price"] for t in p["targets"]]
    assert all(on(x, tick(x, "HOSE")) for x in prices), prices
    assert p["stop"] == 29.9                                    # 29.919 làm tròn xuống bước 50đ
    assert p["entry_lo"] <= 32.2 <= p["entry_hi"] and p["in_zone"]
    p = analyse(load("DPG"), IDX, "HNX")["plan"]                # HNX: bước 100đ
    assert all(on(x, 0.1) for x in [p["entry_lo"], p["entry_hi"], p["stop"]] + [t["price"] for t in p["targets"]])
    assert tick(9.99, "HOSE") == 0.01 and tick(49.95, "HOSE") == 0.05 and tick(50, "HOSE") == 0.1


def test_tch_plan_is_backup_not_chase():
    p = analyse(load("TCH"), IDX)["plan"]
    assert p["kind"] == "Backup" and p["entry_hi"] < 13.9      # không mua đuổi ở giá hiện tại


def test_plan_has_steps_and_cancel():
    p = analyse(load("DPG"), IDX)["plan"]
    assert len(p["steps"]) == 3 and "1/3" in p["steps"][0]
    assert "triệu cp" in p["trigger"] and "triệu cp" in p["cancel"]
    from app.fmt import price
    assert price(p["stop"]) in p["cancel"]


def test_selloff_detected_and_delays_lps():
    from app.core.plan import selloff
    R = load("DPG")
    assert selloff(R) is None
    x = R[-1]; v20 = sum(y["v"] for y in R[-20:]) / 20
    R2 = R + [dict(d="2099-01-02", o=x["c"], h=x["c"] * 1.01, l=x["c"] * 0.95, c=x["c"] * 0.955, v=v20 * 1.4)]
    assert selloff(R2) == "2099-01-02"
    p = analyse(R2, IDX)["plan"]
    if p and p.get("steps"):
        assert p["selloff"] == "2099-01-02" and "bán mạnh" in p["steps"][0]
