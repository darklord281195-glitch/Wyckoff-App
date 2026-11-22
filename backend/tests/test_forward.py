"""Chấm điểm tín hiệu thật: khớp / chờ khớp / không khớp / đã đóng, chỉ tín hiệu báo thật khi live_only."""
import json
from pathlib import Path

from app.core.forward import score
from app.db import connect

FX = Path(__file__).parent / "fixtures"


def setup(tmp_path):
    conn = connect(tmp_path / "t.db")
    R = json.load(open(FX / "TCH.json"))
    conn.executemany("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES ('TCH',?,?,?,?,?,?)",
                     [(r["d"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in R])
    return conn, R


def add_signal(conn, d, plan, replay=0, kind="LPS"):
    conn.execute("INSERT INTO scan_results(date,sym,stage,data) VALUES (?,?,?,?)", (d, "TCH", "D", json.dumps(dict(plan=plan))))
    conn.execute("INSERT INTO signals(date,sym,kind,is_new,text,replay) VALUES (?,?,?,1,'x',?)", (d, "TCH", kind, replay))


def plan_at(c, kind="LPS"):
    return dict(kind=kind, entry_lo=c * 0.98, entry_hi=c * 1.02, stop=c * 0.9, targets=[dict(price=c * 1.1)])


def test_filled_closed_and_unfilled(tmp_path):
    conn, R = setup(tmp_path)
    a, b = R[100], R[150]
    add_signal(conn, a["d"], plan_at(a["c"]))                       # vùng vào quanh giá: khớp phiên sau
    add_signal(conn, b["d"], dict(plan_at(b["c"]), entry_lo=b["c"] * 0.5, entry_hi=b["c"] * 0.55, stop=b["c"] * 0.4))  # quá xa
    add_signal(conn, R[120]["d"], plan_at(R[120]["c"]), replay=1)  # tạo lại: bỏ khi live_only
    conn.commit()
    out = score(conn, live_only=True)
    st = {x["date"]: x for x in out["items"]}
    assert set(st) == {a["d"], b["d"]}
    assert st[a["d"]]["status"] in ("đã đóng", "đang giữ") and st[a["d"]]["R"] is not None
    assert st[a["d"]]["entry_d"] > a["d"]                           # khớp sau ngày báo, không dùng giá cùng phiên
    assert st[b["d"]]["status"] == "không khớp"
    assert out["summary"]["n"] == 2 and out["summary"]["filled"] == 1 and out["summary"]["fill_rate"] == 50
    assert score(conn, live_only=False)["summary"]["n"] == 3


def test_pending_at_end_of_data(tmp_path):
    conn, R = setup(tmp_path)
    last = R[-2]                                                    # báo ở phiên áp chót, giá vào thấp hơn hiện tại
    add_signal(conn, last["d"], dict(plan_at(last["c"]), entry_lo=last["c"] * 0.8, entry_hi=last["c"] * 0.82,
                                     stop=last["c"] * 0.7))
    conn.commit()
    assert score(conn)["items"][0]["status"] == "chờ khớp"
