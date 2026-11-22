"""Dòng tiền ngành: tỷ trọng giá trị giao dịch, phân loại tiền vào / bị xả / tiền rút ra."""
from app.core.flow import sector_flow
from app.db import connect
from app.universe import SCHEMA as LISTING_SCHEMA

DAYS = [f"2026-0{m}-{d:02d}" for m in (1, 2) for d in range(1, 29)][:40]


def test_share_shift_and_labels(tmp_path):
    conn = connect(tmp_path / "t.db")
    conn.executescript(LISTING_SCHEMA)
    conn.executemany("INSERT INTO listing(sym,floor,name,icb,icb_name) VALUES (?,?,?,?,?)",
                     [("AAA", "HOSE", "a", "1", "Ngành A"), ("BBB", "HOSE", "b", "2", "Ngành B"), ("CCC", "HOSE", "c", "3", "Ngành C")])
    rows = []
    for i, d in enumerate(DAYS):
        late = i >= len(DAYS) - 5                              # 5 phiên cuối
        rows.append(("VNINDEX", d, 1000, 1000, 1000, 1000.0, 1))
        rows.append(("AAA", d, 10, 10, 10, 11.0 if late else 10.0, 30 if late else 10))   # GT tăng, giá tăng: tiền vào
        rows.append(("BBB", d, 10, 10, 10, 9.0 if late else 10.0, 30 if late else 10))    # GT tăng, giá giảm: bị xả
        rows.append(("CCC", d, 10, 10, 10, 9.0 if late else 10.0, 5 if late else 30))     # GT giảm, giá giảm: rút ra
    conn.executemany("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    r = sector_flow(conn, 5, 20)
    got = {x["name"]: x for x in r["rows"]}
    assert got["Ngành A"]["label"] == "Tiền vào" and got["Ngành A"]["d_share"] > 0 and got["Ngành A"]["ret"] == 10.0
    assert got["Ngành B"]["label"] == "Bị xả"
    assert got["Ngành C"]["label"] == "Tiền rút ra" and got["Ngành C"]["d_share"] < 0
    assert abs(sum(x["share"] for x in r["rows"]) - 100) < 0.1          # tỷ trọng cộng lại 100%
    assert r["rows"][0]["d_share"] >= r["rows"][-1]["d_share"]           # sắp theo chênh tỷ trọng giảm dần
    assert len(r["heat"][0]["cells"]) == len(r["weeks"]) and r["weeks"][-1] == DAYS[-1]
