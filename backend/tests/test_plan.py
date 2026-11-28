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
    assert "14h15" in p["timing"] and price(p["entry_hi"]) in p["timing"]
    assert price(p["targets"][0]["price"]) in p["take"] and price(p["stop"]) in p["exit"]


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


def test_failed_breakout_switches_to_new_lps():
    from app.core.plan import failed_breakout
    R = load("CTS"); r = analyse(R, IDX); res = r["range"]["res"]
    assert failed_breakout(R, res) is None
    x = R[-1]; v = sum(y["v"] for y in R[-20:]) / 20
    # vượt trần với KL thường (chưa phải SOS), phiên sau đóng cửa lại dưới trần
    R2 = R + [dict(d="2099-01-02", o=x["c"], h=res * 1.02, l=x["c"], c=res * 1.01, v=v * 1.2),
              dict(d="2099-01-03", o=res * 1.01, h=res * 1.01, l=res * 0.985, c=res * 0.99, v=v * 0.8)]
    p = analyse(R2, IDX)["plan"]
    assert p["kind"].startswith("LPS mới")
    assert res * 0.94 <= p["entry_lo"] < p["entry_hi"] < res        # chờ dưới trần, không mua đuổi
    assert p["stop"] < p["entry_lo"] and p["targets"][0]["price"] >= res * 1.02 * 0.999   # T1 = đỉnh cú vượt


def test_scenario_rows_from_filled_trades():
    """Tỷ lệ kịch bản tính trên lệnh đã khớp + đã đóng, cùng cách chia với stats() (dòng '*' khớp backtest_stats)."""
    from app.backtest import scenario_rows, stats
    t = lambda hit, why, R, days, t1_days=None, light="green", open_=False: dict(
        plan="LPS", light=light, hit=hit, why=why, R=R, ret=R, days=days, t1_days=t1_days, open=open_)
    trades = [t(1, "T2", 2.0, 12, t1_days=4), t(1, "Thủng cắt lỗ dời", 0.3, 9, t1_days=6), t(0, "Cắt lỗ", -1.1, 2),
              t(0, "Hết thời gian", -0.2, 20, light="red"), t(0, "đang giữ", 0.5, 3, open_=True)]   # lệnh đang giữ: bỏ
    rows = scenario_rows(trades)
    g = rows[("LPS", "green")]
    assert (g["n"], g["up"], g["flat"], g["down"], g["up_days"], g["down_days"]) == (3, 66.7, 0.0, 33.3, 5.0, 2.0)
    a = rows[("LPS", "*")]
    assert a["n"] == 4 and a["up"] + a["flat"] + a["down"] == 100.0
    s = stats([x for x in trades if not x["open"]])
    assert (a["up"], a["down"], a["flat"], a["avg_r"]) == (s["hit_t1"], s["stop"], s["timeout"], s["avg_r"])
    assert rows[("LPS", "red")]["flat"] == 100.0


def test_slip_for_tick_and_liquidity():
    from app.core.costs import slip_for
    assert slip_for(23.0, 60, "HOSE") == round(0.05 / 2 / 23 + 0.0005, 5)      # nửa bước 50đ + mã rất thanh khoản
    assert slip_for(12.0, 15, "HNX") == round(0.1 / 2 / 12 + 0.003, 5)         # bước 100đ ở giá thấp: đắt hơn nhiều
    assert slip_for(12.0, 15, None) == slip_for(12.0, 15, "UPCOM")              # không rõ sàn: tính bước 100đ
    assert slip_for(80.0, 5, "HOSE") > slip_for(80.0, 30, "HOSE") > slip_for(80.0, 100, "HOSE")


def test_test_kind_spring_needs_new_low_and_reclaim():
    from app.core.wyckoff import test_kind
    b = lambda l, c: dict(l=l, c=c)
    V = [1.0] * 25
    base = [b(10, 10.5)] + [b(10.5, 11)] * 20 + [b(9.9, 10.2)]          # SC 10, rồi một lần thủng xuống 9,9
    assert test_kind(base + [b(9.8, 10.1)], V, 22, 0, 10) == "Spring"   # thấp hơn đáy trước đó, đóng lại trên 10
    assert test_kind(base + [b(9.9, 10.1)], V, 22, 0, 10) == "ST"       # chỉ chạm lại đáy cũ 9,9
    assert test_kind(base + [b(9.7, 9.75)], V, 22, 0, 10) == "Thủng đáy"
    assert test_kind(base + [b(9.7, 9.75)], V[:22] + [2.0], 22, 0, 10) == "SOW"   # KL ≥ 1,5 lần TB20
    assert test_kind(base + [b(10.1, 10.3)], V, 22, 0, 10) == "ST"


def test_phase_b_far_from_ceiling_has_no_entry():
    R = load("CII"); res = analyse(R, IDX)["range"]["res"]
    x = R[-1]; v = sum(y["v"] for y in R[-20:]) / 20
    mid = res * 0.88                                                      # giữa vùng, không test đáy 15 phiên
    R2 = R + [dict(d=f"2099-01-{i + 1:02d}", o=mid, h=mid * 1.01, l=mid * 0.99, c=mid, v=v * 0.7) for i in range(16)]
    p = analyse(R2, IDX)["plan"]
    assert p["kind"] == "Chờ (Pha B)" and p["entry_lo"] is None and not p["take"]


def test_failed_breakout_uses_first_close_above_and_never_falls_back_to_breakout():
    R = load("TCH"); a = analyse(R, IDX); res = a["range"]["res"]
    v = sum(y["v"] for y in R[-20:]) / 20
    bar = lambda d, c: dict(d=d, o=c, h=c * 1.01, l=c * 0.99, c=c, v=v * 0.7)
    # TCH đã ở trên trần từ SOS 04/11; nay đóng cửa lại dưới trần -> nền tính từ trước SOS, không phải từ 20/11
    p = analyse(R + [bar("2099-01-02", res * 1.02), bar("2099-01-05", res * 0.975)], IDX)["plan"]
    assert p["kind"].startswith("LPS mới") and p["entry_lo"] < res * 0.95 and p["targets"][0]["price"] >= 13.9 * 0.999
    # thủng luôn nền trước cú vượt: không quay lại kế hoạch phá trần
    p = analyse(R + [bar("2099-01-02", res * 1.02), bar("2099-01-05", res * 0.9)], IDX)["plan"]
    assert not p["kind"].startswith("Phá trần") and "hỏng" in p["trigger"]


def test_spring_test_targets_ceiling_before_cause_effect():
    a = analyse(load("DIG"), IDX); p = a["plan"]; res = a["range"]["res"]
    assert p["kind"] == "Spring/Test"
    main = next(t for t in p["targets"] if t["k"] == p["main_target"])
    assert abs(main["price"] - res) < res * 0.01                          # lời/lỗ tính tới trần vùng
    assert all(t["price"] >= res * 0.99 for t in p["targets"] if t["ce"])  # Nhân–Quả nằm sau trần
