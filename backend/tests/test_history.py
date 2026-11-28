"""Xem lại phiên cũ: quét lại một phiên từ dữ liệu đã có (không Telegram) và API nhận ngày."""
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from app import api, scan, notify  # noqa: E402
from app.db import connect  # noqa: E402

FX = Path(__file__).parent / "fixtures"
SYMS = ["TCH", "DPG", "CTS"]


def _db(tmp_path):
    conn = connect(tmp_path / "t.db")
    for s in ["VNINDEX", *SYMS]:
        conn.executemany("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES (?,?,?,?,?,?,?)",
                         [(s, r["d"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in json.load(open(FX / f"{s}.json"))])
    conn.commit()
    return conn


def test_scan_past_session_uses_only_data_until_then(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    monkeypatch.setattr(scan, "connect", lambda: conn)
    def boom(*a, **k):
        raise AssertionError("không được gửi Telegram khi quét phiên cũ")
    monkeypatch.setattr(notify, "send_text", boom)
    monkeypatch.setattr(notify, "enabled", lambda: True)

    r = scan.run(symbols=SYMS, at="2026-10-15")
    assert r["date"] == "2026-10-15" and r["n"] == len(SYMS)
    for (data,) in conn.execute("SELECT data FROM scan_results WHERE date='2026-10-15'"):
        assert json.loads(data)["d"] == "2026-10-15"            # nến cuối đúng phiên, không lấy nến sau đó
    assert not conn.execute("SELECT 1 FROM telegram_sent").fetchone()

    try:
        scan.run(symbols=SYMS, at="2026-10-18")                   # chủ nhật
        assert False, "phải báo lỗi ngày không giao dịch"
    except ValueError:
        pass


def test_api_session_dates(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    for d, kind in [("2026-11-13", "LPS"), ("2026-11-20", "SOS")]:
        conn.execute("INSERT INTO scan_results(date,sym,stage,data) VALUES (?,?,?,?)",
                     (d, "TCH", "D", json.dumps(dict(tag="D-LPS", stage="D", c=1, chg=0, liq=20, plan=None))))
        conn.execute("INSERT INTO signals(date,sym,kind,is_new,text) VALUES (?,?,?,?,?)", (d, "TCH", kind, 1, "TCH x"))
    conn.commit()
    monkeypatch.setattr(api, "conn", conn)
    c = TestClient(api.app)

    assert c.get("/api/scan/dates").json() == ["2026-11-20", "2026-11-13"]
    assert c.get("/api/scan/latest").json()["date"] == "2026-11-20"
    assert c.get("/api/scan/latest?date=2026-11-13").json()["date"] == "2026-11-13"
    assert c.get("/api/scan/latest?date=2026-11-14").status_code == 404
    assert [s["kind"] for s in c.get("/api/signals?days=0&until=2026-11-13").json()] == ["LPS"]
    assert [s["kind"] for s in c.get("/api/signals?days=30").json()] == ["SOS", "LPS"]

    s = c.get("/api/symbols/TCH?at=2026-10-15").json()
    assert s["at"] == "2026-10-15" and s["analysis"]["d"] == "2026-10-15"
    assert s["ohlcv"][-1]["d"] == "2026-11-20"                  # biểu đồ vẫn có nến sau ngày xem
    assert all(x["date"] <= "2026-10-15" for x in s["signals"])


def test_scan_latest_fills_mcdx_for_old_scans(tmp_path, monkeypatch):
    """Bản quét trước khi có MCDX (không có trường mcdx): API tự tính từ giá đóng cửa, khớp cách tính của scan.py."""
    from app.core import mcdx
    from app.core.data import get_ohlcv
    conn = _db(tmp_path)
    d = conn.execute("SELECT max(d) FROM ohlcv WHERE sym='TCH'").fetchone()[0]
    conn.execute("INSERT INTO scan_results(date,sym,stage,data) VALUES (?,?,?,?)",
                 (d, "TCH", "D", json.dumps(dict(tag="D-LPS", stage="D", c=1, chg=0, liq=20, plan=None))))
    conn.commit()
    monkeypatch.setattr(api, "conn", conn)
    monkeypatch.setattr(api, "_MCDX_CACHE", {})
    row = TestClient(api.app).get("/api/scan/latest").json()["rows"][0]
    want = mcdx.last([x["c"] for x in get_ohlcv(conn, "TCH", 500, refresh=False)])
    assert row["banker"] == want["banker"] and row["banker_label"] == want["label"]


def test_symbol_range_limits_wyckoff_search(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    monkeypatch.setattr(api, "conn", conn)
    c = TestClient(api.app)
    s = c.get("/api/symbols/TCH?from=2026-06-01&at=2026-09-30").json()
    a = s["analysis"]
    assert s["start"] == "2026-06-01" and a["d"] == "2026-09-30"
    if a["range"]:                                               # vùng tìm được nằm trong khoảng chọn
        assert "2026-06-01" <= a["range"]["start"] <= "2026-09-30"
    assert all(e["d"] <= "2026-09-30" for e in a["events"])
    assert c.get("/api/symbols/TCH?from=2026-09-30&at=2026-06-01").status_code == 400


def test_foreign_cached_and_refetched(tmp_path):
    from app.core.foreign import get_foreign
    conn = _db(tmp_path)
    calls = []
    def fake(sym, end=None, size=110):
        calls.append(end)
        days = [r[0] for r in conn.execute("SELECT d FROM ohlcv WHERE sym=? AND d<=? ORDER BY d DESC LIMIT 100",
                                           (sym, end or "9999"))]
        return [dict(d=d, buy=2.0, sell=1.0, net=1.0, net_vol=100, room=10, total_room=20) for d in days]
    rows, err = get_foreign(conn, "TCH", None, 90, fetcher=fake)
    assert err is None and len(rows) == 90 and rows[-1]["d"] == "2026-11-20" and rows[0]["d"] < rows[-1]["d"]
    get_foreign(conn, "TCH", None, 90, fetcher=fake)
    assert len(calls) == 1                                       # đủ dữ liệu -> không tải lại
    rows, _ = get_foreign(conn, "TCH", "2026-10-15", 90, fetcher=fake)
    assert rows[-1]["d"] == "2026-10-15" and len(rows) == 90
    def broken(sym, end=None, size=0):
        raise OSError("mất mạng")
    rows, err = get_foreign(conn, "DPG", None, fetcher=broken)
    assert rows == [] and "mất mạng" in err
