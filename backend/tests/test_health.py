"""Sức khỏe hệ thống (health.status, watchdog) và nguồn dữ liệu dự phòng (chỉ nối thêm phiên mới, khớp giá cũ)."""
import datetime as dt
import json

from app import health
from app.core import data
from app.db import connect

VN = health.VN
at = lambda y, m, d, hh=10, mm=0: dt.datetime(y, m, d, hh, mm, tzinfo=VN)


def test_expected_session():
    assert health.expected_session(at(2026, 11, 30, 10)) == "2026-11-27"     # thứ 2 buổi sáng: phiên thứ 6
    assert health.expected_session(at(2026, 11, 30, 16, 30)) == "2026-11-30"  # thứ 2 sau 16:00: phiên hôm nay
    assert health.expected_session(at(2026, 11, 28)) == "2026-11-27"         # thứ 7


def _db(tmp_path, scanned="2026-11-27"):
    conn = connect(tmp_path / "t.db")
    for d in ("2026-11-26", "2026-11-27"):
        conn.execute("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES ('VNINDEX',?,1,1,1,1,1)", (d,))
        conn.execute("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES ('AAA',?,1,1,1,1,1)", (d,))
    conn.execute("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES ('BBB','2026-11-26',1,1,1,1,1)")       # BBB thiếu phiên 27/11
    for s in ("VNINDEX", "AAA", "BBB"):
        conn.execute("INSERT INTO scan_results(date,sym,stage,data) VALUES (?,?,?,?)", (scanned, s, "", json.dumps(dict(liq=50))))
    conn.commit()
    return conn


def _by_key(st):
    return {c["key"]: c for c in st["checks"]}


def test_status_levels(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "BACKUP_DIR", tmp_path / "khong-co")
    conn = _db(tmp_path)
    health.record(conn, "scan", "2026-11-27T15:30:00+07:00", "ok",
                  dict(date="2026-11-27", n=3, signals=0, errors=["XYZ"], n_errors=1, fallback=["AAA"]))
    st = health.status(conn, at(2026, 11, 28), tasks=lambda: None)          # không phải Windows: bỏ mục task
    c = _by_key(st)
    assert c["scan"]["level"] == "ok" and c["errors"]["level"] == "warn" and "XYZ" in c["errors"]["detail"]
    assert c["fallback"]["level"] == "warn" and "AAA" in c["fallback"]["detail"]
    assert c["data"]["level"] == "warn" and "BBB" in c["data"]["detail"]    # mã thanh khoản chưa có phiên mới nhất
    assert c["backup"]["level"] == "warn" and "tasks" not in c and st["level"] == "warn"
    st2 = health.status(conn, at(2026, 11, 30, 17), tasks=lambda: {})       # thứ 2 17h chưa quét; máy chưa có task
    c2 = _by_key(st2)
    assert c2["scan"]["level"] == "error" and st2["level"] == "error" and c2["tasks"]["level"] == "warn"
    health.record(conn, "scan", "2026-11-30T15:30:00+07:00", "skipped", dict(date="2026-11-27", n=0, signals=0, errors=[]))
    assert _by_key(health.status(conn, at(2026, 11, 30, 17), tasks=lambda: None))["scan"]["level"] == "warn"   # nghỉ lễ


def test_task_results(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "BACKUP_DIR", tmp_path)
    conn = _db(tmp_path)
    t = lambda name, result: dict(name=name, state="Ready", last="2026-11-27T15:30:00", result=result, next="2026-11-30T15:30:00")
    tasks = {"Wyckoff Scanner": t("Wyckoff Scanner", 1), "Wyckoff Intraday": t("Wyckoff Intraday", 0)}
    c = _by_key(health.status(conn, at(2026, 11, 28), tasks=lambda: tasks))
    assert c["task:Wyckoff Scanner"]["level"] == "error" and "0x00000001" in c["task:Wyckoff Scanner"]["detail"]
    assert c["task:Wyckoff Intraday"]["level"] == "ok" and c["task:Wyckoff Watchdog"]["level"] == "warn"   # chưa đăng ký


def test_notify_errors_once_a_day(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    sent = []
    monkeypatch.setattr(health.notify, "enabled", lambda: True)
    monkeypatch.setattr(health.notify, "send_text", sent.append)
    st = dict(checks=[dict(key="scan", label="Quét cuối ngày", level="error", detail="chưa quét phiên 30/11")])
    assert health.notify_errors(conn, st, at(2026, 11, 30, 16, 30)) and "chưa quét" in sent[0]
    assert not health.notify_errors(conn, st, at(2026, 11, 30, 17))              # đã gửi hôm nay
    assert not health.notify_errors(conn, dict(checks=[]), at(2026, 12, 1))       # không có lỗi


def test_fallback_only_appends_matching_rows(tmp_path):
    conn = connect(tmp_path / "t.db")
    conn.executemany("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES ('VNINDEX',?,10,10,10,?,?)",
                     [("2026-11-25", 1600.0, 400.0), ("2026-11-26", 1610.0, 500.0)])
    conn.commit()
    fb = [dict(d="2026-11-25", o=1, h=1, l=1, c=1600.0, v=520.0), dict(d="2026-11-26", o=1, h=1, l=1, c=1610.0, v=650.0),
          dict(d="2026-11-27", o=1, h=1, l=1, c=1620.0, v=780.0)]
    new = data.merge_fallback(conn, "VNINDEX", fb, "2026-11-26")
    assert [r["d"] for r in new] == ["2026-11-27"] and abs(new[0]["v"] - 600.0) < 1e-6   # KL quy đổi theo tỷ lệ ~0,77
    bad = [dict(r, c=r["c"] * 1.02) for r in fb]                                          # lệch thang giá (điều chỉnh khác)
    assert data.merge_fallback(conn, "VNINDEX", bad, "2026-11-26") is None
    assert data.merge_fallback(conn, "VNINDEX", fb, None) is None                          # chưa có lịch sử để đối chiếu


def test_sync_many_uses_fallback_rows_append_only(tmp_path, monkeypatch):
    conn = connect(tmp_path / "t.db")
    conn.executemany("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES (?,?,10,10,10,10,1)",
                     [(s, d) for s in ("AAA", "BBB") for d in ("2026-11-26", "2026-11-27")])
    conn.commit()

    def fake(sym, days, retries=3, res="D"):
        rows = data.Rows([dict(d="2026-11-27", o=10, h=10, l=10, c=10 if sym == "AAA" else 12, v=1.0),
                          dict(d="2026-11-28", o=10, h=11, l=10, c=11, v=2.0)])
        rows.src = "dnse"
        return rows
    monkeypatch.setattr(data, "fetch_remote", fake)
    errors = data.sync_many(conn, ["AAA", "BBB"], 500)
    assert errors == ["BBB"]                                                   # BBB lệch giá: bỏ, báo lỗi
    got = conn.execute("SELECT sym, d, c FROM ohlcv WHERE d='2026-11-28' ORDER BY sym").fetchall()
    assert [tuple(r) for r in got] == [("AAA", "2026-11-28", 11.0)]
    assert conn.execute("SELECT count(*) FROM ohlcv WHERE sym='BBB'").fetchone()[0] == 2   # dữ liệu cũ của BBB còn nguyên
