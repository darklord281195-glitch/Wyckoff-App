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
