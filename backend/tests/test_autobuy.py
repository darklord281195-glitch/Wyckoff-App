"""Tự mua thử nghiệm 14h10: điều kiện "Kịch bản mua đẹp" (good_setup), ghi sổ thử nghiệm (auto_buy) và chấm kết quả (paper)."""
import datetime as dt
import json

from app import intraday as it
from app.core import paper
from app.db import connect

TODAY = "2026-11-30"
NOW = dt.datetime(2026, 11, 30, 14, 20, tzinfo=it.VN)
PLAN = dict(kind="LPS", entry_lo=9.9, entry_hi=10.3, stop=9.5, rr=3.0, targets=[dict(k="T1", price=11.0)], selloff=None)


def bars(n=25, today=None):
    R = [dict(d=(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat(), o=10, h=10.1, l=9.9, c=10.0, v=1.0)
         for i in range(n)]
    return R + [dict(dict(d=TODAY, o=10.0, h=10.25, l=9.9, c=10.2, v=0.5), **(today or {}))]


def test_good_setup_rules():
    ok = lambda plan=None, **today: it.good_setup(dict(PLAN, **(plan or {})), bars(today=today))
    assert ok() == (True, "LPS · KL x0,5 · lời/lỗ 3,0")
    assert "ngoài vùng" in ok(c=10.4, h=10.45)[1]                          # đã vượt cận trên: không mua đuổi
    assert "nửa dưới" in ok(c=10.0, h=10.3)[1]
    assert "quay đầu" in ok(c=9.98, h=10.0)[1]                             # LPS cần đóng cửa tăng
    assert ok(plan=dict(kind="Spring/Test"), c=9.98, h=10.0)[0]           # phiên Test không cần tăng giá
    assert "KL" in ok(v=0.9)[1]
    assert "lời/lỗ" in ok(plan=dict(rr=1.8))[1]
    assert not ok(plan=dict(kind="Không vào"))[0]
    # vừa bán mạnh: cần ≥ 2 phiên lùi KL thấp sau phiên đó (tính cả hôm nay)
    R = bars()
    assert "bán mạnh" in it.good_setup(dict(PLAN, selloff=R[-2]["d"]), R)[1]
    assert "bán mạnh" in it.good_setup(dict(PLAN, selloff=R[-3]["d"]), R)[1]     # phiên giữa KL = TB20: chưa cạn
    R[-2]["v"] = 0.6
    assert it.good_setup(dict(PLAN, selloff=R[-3]["d"]), R)[0]
    brk = dict(PLAN, kind="Phá trần (SOS)")
    assert "KL" in it.good_setup(brk, bars(), res=10.1)[1]
    assert it.good_setup(brk, bars(today=dict(v=1.4)), res=10.1)[0]


def _db(tmp_path):
    conn = connect(tmp_path / "t.db")
    for s in ("AAA", "BBB", "VNINDEX"):
        conn.executemany("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES (?,?,?,?,?,?,?)",
                         [(s, b["d"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in bars(130)[:-1]])
        conn.execute("INSERT INTO scan_results(date,sym,stage,data) VALUES (?,?,?,?)",
                     ("2026-11-27", s, "", json.dumps(dict(liq=50, breadth=40))))
    conn.commit()
    return conn


def test_auto_buy_writes_paper_book_once_and_not_portfolio(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    plans = {"AAA": PLAN, "BBB": dict(PLAN, rr=2.5)}
    monkeypatch.setattr(it, "get_ohlcv", lambda c, s, d, refresh: [dict(r) for r in conn.execute(
        "SELECT d,o,h,l,c,v FROM ohlcv WHERE sym=? ORDER BY d", (s,))])
    monkeypatch.setattr(paper, "get_ohlcv", it.get_ohlcv)
    # analyse(R, IDX, floor) không cho biết mã: ghép mã qua nến hôm nay
    monkeypatch.setattr(it, "analyse", lambda R, *a: dict(plan=plans.get(R[-1].get("sym")), range=dict(res=11)))
    monkeypatch.setattr(it, "traffic_light", lambda *a: dict(light="red"))
    fetch = lambda s, days: [dict(bars()[-1], sym=s)]

    lines = it.auto_buy(conn, fetch=fetch, now=NOW, log=lambda *a: None)
    assert [x.split()[1] for x in lines] == ["AAA", "BBB"]               # lời/lỗ cao xếp trước
    t = [dict(r) for r in conn.execute("SELECT sym, d, at, entry_px, stop, light, vx, close_pos FROM paper_trades ORDER BY sym")]
    assert t[0] == dict(sym="AAA", d=TODAY, at="14:20", entry_px=10.2, stop=9.5, light="red", vx=0.5, close_pos=0.86)
    assert conn.execute("SELECT count(*) FROM positions").fetchone()[0] == 0      # không đụng Danh mục thật
    assert it.auto_buy(conn, fetch=fetch, now=NOW, log=lambda *a: None) == []     # không mua trùng trong ngày
    # hôm sau: lệnh hôm qua chưa bán hết -> không mua chồng
    conn.execute("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES ('AAA',?,10,10.25,9.9,10.2,0.5)", (TODAY,))
    conn.commit()
    assert "AAA" in paper.open_syms(conn)


def test_paper_evaluate_stop_and_target():
    t = dict(d="2026-12-01", entry_px=10.0, stop=9.5, targets=[11.0, 12.0])
    b = lambda d, h, l, c: dict(d=d, o=c, h=h, l=l, c=c, v=1)
    lose = paper.evaluate(t, [b("2026-12-01", 10.1, 9.9, 10), b("2026-12-02", 10, 9.3, 9.4),
                              b("2026-12-03", 9.4, 9.2, 9.3)])
    assert lose["status"] == "đã đóng" and lose["exit_why"] == "Cắt lỗ" and lose["R"] == -1.57   # T+2: bán chiều phiên 3 ở 9,3 -> lỗ hơn 1R
    win = paper.evaluate(t, [b("2026-12-01", 10.1, 9.9, 10), b("2026-12-02", 10.5, 10, 10.4),
                             b("2026-12-03", 12.2, 10.4, 12.1)])
    assert win["status"] == "đã đóng" and win["hit_t1"] and win["R"] > 2
    assert paper.evaluate(t, [b("2026-11-30", 10, 10, 10)])["status"] == "chờ dữ liệu"     # chưa có nến phiên mua
