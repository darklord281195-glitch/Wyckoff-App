"""Trượt giá + khoảng tin cậy trong backtest, thống kê theo kế hoạch ở API, khối ngoại lúc quét (fx10)."""
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from app import api, backtest  # noqa: E402
from app.core.foreign import sync_foreign, net_sum  # noqa: E402
from app.db import connect  # noqa: E402

FX = Path(__file__).parent / "fixtures"
load = lambda s: json.load(open(FX / f"{s}.json"))


def test_slippage_lowers_every_trade():
    IDX = load("VNINDEX")
    base, slipped = [], []
    for s in ["TCH", "DPG", "CTS", "DIG", "CII"]:
        R = load(s)
        base += backtest.run_symbol(s, R, IDX, slip=0)
        slipped += backtest.run_symbol(s, R, IDX, slip=0.0025)
    assert base, "fixture phải sinh ít nhất một lệnh"
    assert len(base) == len(slipped)                      # trượt giá không đổi điểm vào/ra, chỉ đổi lời/lỗ
    for a, b in zip(base, slipped):
        assert (a["sym"], a["entry_d"], a["exit_d"]) == (b["sym"], b["entry_d"], b["exit_d"])
        assert b["ret"] < a["ret"] and b["R"] <= a["R"]


def test_stats_confidence_interval():
    xs = [dict(R=r, ret=r, days=10, why="Cắt lỗ" if r < 0 else "Chạm T1", hit=int(r > 0), open=False)
          for r in [1.0, -1.0, 2.0, -1.0, 0.5]]
    s = backtest.stats(xs)
    assert s["n"] == 5 and s["avg_r"] == 0.3 and s["ci_lo"] < 0.3 < s["ci_hi"]
    assert s["stop"] == 40.0 and s["hit_t1"] == 60.0 and s["win"] == 60.0


def test_save_stats_and_api_plan_stats(tmp_path, monkeypatch):
    conn = connect(tmp_path / "t.db")
    for s in ["VNINDEX", "TCH"]:
        conn.executemany("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES (?,?,?,?,?,?,?)",
                         [(s, r["d"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in load(s)])
    trades = [dict(plan="Backup", R=1.0, ret=5, days=12, why="Chạm T1", hit=1, open=False),
              dict(plan="Backup", R=-1.0, ret=-5, days=6, why="Cắt lỗ", hit=0, open=False),
              dict(plan="Phá trần (SOS)", R=0.5, ret=2, days=9, why="Hết thời gian", hit=0, open=False)]
    backtest.save_stats(conn, trades, "2019–2026", 0.25)
    got = {r["plan"]: dict(r) for r in conn.execute("SELECT * FROM backtest_stats")}
    assert set(got) == {"Backup", "Phá trần", "Tất cả"} and got["Backup"]["n"] == 2 and got["Tất cả"]["n"] == 3

    monkeypatch.setattr(api, "conn", conn)
    s = TestClient(api.app).get("/api/symbols/TCH").json()
    kind = (s["analysis"].get("plan") or {}).get("kind") or ""
    want = got.get(kind.split(" (")[0])
    assert (s["plan_stats"] or None) == (want or None)       # đúng dòng của loại kế hoạch hiện tại, hoặc None


def test_sync_foreign_only_missing_and_net_sum(tmp_path):
    conn = connect(tmp_path / "t.db")
    days = ["2026-11-%02d" % d for d in (3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 17, 18, 19, 20)]
    calls = []
    def fake(sym, end=None, size=110):
        calls.append((sym, size))
        if sym == "BAD":
            raise OSError("lỗi mạng")
        return [dict(d=d, buy=2.0, sell=1.0, net=1.0, net_vol=1, room=1, total_room=2) for d in days[::-1]]
    assert sync_foreign(conn, ["AAA", "BAD"], "2026-11-20", fetcher=fake) == ["BAD"]
    assert ("AAA", 110) in calls                              # chưa có gì -> tải dài
    calls.clear()
    assert sync_foreign(conn, ["AAA"], "2026-11-20", fetcher=fake) == [] and calls == []   # đã đủ -> không tải
    assert net_sum(conn, "AAA", "2026-11-20") == 10.0
    assert net_sum(conn, "AAA", "2026-11-21") is None         # thiếu phiên 21/11 -> không báo số cũ
    assert net_sum(conn, "AAA", "2026-11-06") is None         # chưa đủ 10 phiên


def test_sector_medians_and_rs():
    from collections import defaultdict
    acc = defaultdict(list)
    idx = {f"2026-01-{d:02d}": 100.0 for d in range(1, 32)}
    # mã tăng 10% trong 20 phiên, VNINDEX đứng yên -> RS20 = +10; GT đủ lớn để qua ngưỡng thanh khoản
    R = [dict(d=f"2026-01-{d:02d}", o=10, h=10, l=10, c=10 + (d > 21), v=10) for d in range(1, 32)]
    backtest.add_sector_rs(R, idx, "8600", acc)
    backtest.add_sector_rs(R, idx, None, acc)                 # mã không có ngành: bỏ qua
    assert all(k[0] == "8600" for k in acc) and round(acc[("8600", "2026-01-22")][0], 1) == 10.0
    med = backtest.sector_medians({("x", "d"): [1, 5, 3], ("y", "d"): [1, 2]})
    assert med == {("x", "d"): 3}                              # nhóm < 3 mã bị bỏ


def test_backfill_foreign_requests_long_history(tmp_path):
    from app.core.foreign import backfill_foreign, HISTORY_SESSIONS
    conn = connect(tmp_path / "t.db")
    asked = []
    def fake(sym, end=None, size=0):
        asked.append(size)
        return [dict(d="2026-11-20", buy=1.0, sell=0.0, net=1.0, net_vol=1, room=1, total_room=1)]
    assert backfill_foreign(conn, ["AAA", "BBB"], fetcher=fake) == []
    assert asked == [HISTORY_SESSIONS] * 2 and conn.execute("SELECT count(*) FROM foreign_trade").fetchone()[0] == 2


def test_sector_stats_and_api(tmp_path, monkeypatch):
    from app.core import sectors
    lst = {s: dict(icb="8600", icb_name="Bất động sản") for s in ("A1", "A2", "A3")} | {"B1": dict(icb="8300", icb_name="Ngân hàng")}
    res = {"A1": dict(liq=20, rs20=5, rs60=1, stage="D", fx10=2.0), "A2": dict(liq=20, rs20=-1, rs60=3, stage="BC", fx10=None),
           "A3": dict(liq=20, rs20=3, rs60=2, stage="near", fx10=-1.0), "B1": dict(liq=50, rs20=9, rs60=9, stage="D", fx10=5.0),
           "A4": dict(liq=1, rs20=99, rs60=99, stage="D")}                      # kém thanh khoản: bỏ
    rows = sectors.sector_stats(res, lst, 10)
    assert rows == [dict(icb="8600", name="Bất động sản", n=3, rs20=3, rs60=2, pct_d=67, fx10=1.0)]   # Ngân hàng < 3 mã
    conn = connect(tmp_path / "t.db")
    conn.execute("INSERT INTO scan_results(date,sym,stage,data) VALUES ('2026-11-20','A1','D','{}')")
    sectors.save(conn, "2026-11-20", rows); conn.commit()
    monkeypatch.setattr(api, "conn", conn)
    got = TestClient(api.app).get("/api/sectors").json()
    assert got["date"] == "2026-11-20" and got["rows"][0]["name"] == "Bất động sản"


def test_fundamentals_point_in_time():
    from app.core import fundamentals as F
    rows = []
    for i, (f, created) in enumerate([("2025-03-31", "2025-04-25"), ("2025-06-30", "2025-07-25"), ("2025-09-30", "2025-10-25"),
                                      ("2025-12-31", "2026-01-25"), ("2026-03-31", "2026-04-25"), ("2026-06-30", "2026-07-25"),
                                      ("2026-09-30", "2026-10-25"), ("2026-12-31", "2027-01-25")]):
        rows += [dict(fiscal=f, created=created, item="np", value=10.0 + i * 0 + (5 if i >= 4 else 0)),
                 dict(fiscal=f, created=created, item="equity", value=100.0),
                 dict(fiscal=f, created=created, item="debt_st", value=20.0)]
    m = F.metrics_at(rows, "2026-11-20")              # quý 4/2026 công bố 25/01/2027: chưa được dùng
    assert m["fiscal"] == "2026-09-30"
    assert m["np_ttm"] == 15 + 15 + 15 + 10           # 4 quý: Q4/25 (10) + Q1–Q3/26 (15)
    assert m["np_growth"] is None                     # thiếu quý 4/2024 để có 4 quý trước đó
    m2 = F.metrics_at(rows)                           # không giới hạn ngày: Q1–Q4/2026 = 60 so với 40
    assert m2["np_ttm"] == 60 and m2["np_growth"] == 50.0 and m2["roe"] == 60.0 and m2["debt_equity"] == 0.2
    assert F.metrics_at(rows, "2025-01-01") is None   # chưa có báo cáo nào được công bố


def test_quarters_back():
    from app.core.fundamentals import _quarters_back
    assert _quarters_back("2026-09-30", 4) == "2025-09-30" and _quarters_back("2026-03-31", 1) == "2025-12-31"


def test_listing_api(tmp_path, monkeypatch):
    from app.universe import SCHEMA as LISTING_SCHEMA
    conn = connect(tmp_path / "t.db")
    conn.executescript(LISTING_SCHEMA)
    conn.executemany("INSERT INTO listing(sym,floor,name) VALUES (?,?,?)", [("HPG", "HOSE", "Hòa Phát"), ("ACB", "HOSE", "ACB")])
    conn.commit()
    monkeypatch.setattr(api, "conn", conn)
    got = TestClient(api.app).get("/api/listing").json()
    assert [x["sym"] for x in got] == ["VNINDEX", "ACB", "HPG"] and got[2]["name"] == "Hòa Phát"
