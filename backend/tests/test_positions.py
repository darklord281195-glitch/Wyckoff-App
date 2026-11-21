"""Luật quản lý lệnh (positions.simulate) trên nến giả, và backtest không nhìn trước tương lai."""
import datetime as dt
import json
from pathlib import Path
from app.core.positions import simulate
from app.backtest import run_symbol

FX = Path(__file__).parent / "fixtures"
load = lambda s: json.load(open(FX / f"{s}.json"))


def B(*rows):
    """rows: (o, h, l, c) -> OHLCV ngày tăng dần."""
    d0 = dt.date(2026, 1, 1)
    return [dict(d=(d0 + dt.timedelta(days=i)).isoformat(), o=o, h=h, l=l, c=c, v=1.0)
            for i, (o, h, l, c) in enumerate(rows)]


def test_stop_waits_for_t2_settlement():
    bars = B((10, 10, 9.4, 9.4), (9.4, 9.6, 9.0, 9.2), (9.2, 9.5, 9.0, 9.3), (9.3, 9.4, 9.1, 9.2))
    s = simulate(10, 9.5, [11, 12, 13], bars)
    assert "chiều T+2" in s["events"][0]["text"]                  # thủng ngay phiên mua: chưa bán được
    assert s["exits"] == [dict(d=bars[2]["d"], px=9.3, frac=1.0, why="Cắt lỗ")]   # bán ở giá đóng cửa phiên T+2
    assert not s["open"]


def test_t1_breakeven_then_trailing_stop():
    bars = B((10, 10.2, 9.9, 10.1), (10.1, 10.5, 10.0, 10.4), (10.4, 10.8, 10.3, 10.7),
             (10.8, 11.2, 10.7, 11.0),                               # chạm T1 11: bán 1/3, cắt lỗ về giá vốn 10
             *[(11.2, 11.5, 10.9, 11.3)] * 9,                        # đáy nâng -> dời cắt lỗ lên 10,3 rồi 10,7
             (11.0, 11.1, 10.5, 10.6),                               # đóng cửa dưới 10,7
             (10.5, 10.6, 10.2, 10.3))                               # bán phần còn lại ở giá mở cửa
    s = simulate(10, 9.5, [11, 12, 13], bars)
    assert [(x["why"], x["px"], round(x["frac"], 3)) for x in s["exits"]] == [("T1", 11, 0.333),
                                                                              ("Thủng cắt lỗ dời", 10.5, 0.667)]
    assert [e["text"].split(" (")[0] for e in s["events"] if e["kind"] == "Dời cắt lỗ"] == \
        ["dời cắt lỗ lên 10.300", "dời cắt lỗ lên 10.700"]
    assert "dời cắt lỗ về giá vốn 10.000" in s["events"][0]["text"] and not s["open"]


def test_time_stop_and_gap_over_target():
    bars = B(*[(10, 10.2, 9.8, 10)] * 22)                         # 20 phiên đi ngang, chưa chạm T1
    assert simulate(10, 9, [12], bars)["exits"] == [dict(d=bars[21]["d"], px=10, frac=1.0, why="Hết thời gian")]
    s = simulate(10, 9.5, [11], B((10, 10, 10, 10), (10, 10, 10, 10), (10, 10, 10, 10), (11.5, 11.8, 11.4, 11.6)))
    assert s["exits"] == [dict(d=s["exits"][0]["d"], px=11.5, frac=1.0, why="T1")]   # mở cửa vượt mục tiêu duy nhất


def test_backtest_does_not_peek(monkeypatch):
    """Lệnh đã đóng khi chạy với dữ liệu cắt ngắn phải giống hệt khi chạy với đủ dữ liệu."""
    from app.core import signals
    monkeypatch.setattr(signals, "READY_BUY", 0)                   # mở hết bộ lọc điểm để có đủ lệnh mà so
    IDX = load("VNINDEX")
    key = lambda t: (t["sig_d"], t["entry_d"], t["entry"], t["exit_d"], t["R"])
    for s in ("CTS", "DIG"):                                       # hai mã có lệnh đã đóng trước 40 phiên cuối
        R = load(s)
        full, cut = run_symbol(s, R, IDX), run_symbol(s, R[:-40], IDX)
        closed = {key(t) for t in cut if not t["open"]}
        assert closed and closed <= {key(t) for t in full}, s
        for t in full:
            assert t["sig_d"] < t["entry_d"] <= t["exit_d"] and t["entry"] >= t["stop"], t


def test_intraday_check():
    from app.intraday import check, in_session, VN
    import datetime as dt
    bar = dict(o=13.0, h=13.4, l=12.8, c=13.1)
    kinds = lambda **k: [x[0] for x in check(bar, **k)]
    assert kinds(stop=12.9, target=13.3) == ["stop", "target"]
    assert kinds(stop=12.5, target=14) == []
    assert kinds(plan=dict(entry_lo=13.3, entry_hi=13.6, kind="LPS")) == ["zone"]       # chạm cận dưới vùng
    assert kinds(plan=dict(entry_lo=13.5, entry_hi=13.6, kind="LPS")) == []
    t = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=VN)
    assert in_session(t("2026-11-20 10:00")) and not in_session(t("2026-11-20 12:00")) and not in_session(t("2026-11-21 10:00"))
