"""Bán từng phần: ghi lịch sử, chặn bán quá số còn giữ, bán hết thì đóng lệnh với giá bình quân."""
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from app import api  # noqa: E402
from app.db import connect  # noqa: E402


def test_sell_partial_then_all(tmp_path, monkeypatch):
    conn = connect(tmp_path / "t.db")
    conn.execute("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES ('VIX','2026-11-20',12.5,12.9,12.5,12.7,1)")
    conn.execute("INSERT INTO positions(id,sym,entry_d,entry_px,qty,stop) VALUES (1,'VIX','2026-11-13',13.1,100,11.8)")
    conn.commit()
    monkeypatch.setattr(api, "conn", conn)
    c = TestClient(api.app)

    assert c.post("/api/positions/1/sell", json={"qty": 200}).status_code == 400
    assert c.post("/api/positions/1/sell", json={"qty": 40, "px": 14, "d": "2026-11-18"}).status_code == 200
    assert conn.execute("SELECT status FROM positions WHERE id=1").fetchone()[0] == "open"
    c.post("/api/positions/1/sell", json={})                       # phần còn lại: 60 cp ở giá đóng cửa 12,7
    st, px = conn.execute("SELECT status, exit_px FROM positions WHERE id=1").fetchone()
    assert st == "closed" and abs(px - (40 * 14 + 60 * 12.7) / 100) < 1e-9
    s = c.get("/api/sales").json()
    assert [x["qty"] for x in s] == [60, 40] and s[1]["pnl"] > 0 > s[0]["pnl"]

    c.delete(f"/api/sales/{s[0]['id']}")                            # xóa lần bán cuối -> lệnh mở lại, còn 60 cp
    p = c.get("/api/positions").json()
    assert len(p) == 1 and p[0]["sold"] == 40 and p[0]["exit_px"] is None
    assert c.delete("/api/sales/999").status_code == 404


def test_scan_allowed_only_after_close_weekdays():
    t = lambda s: api.dt.datetime.fromisoformat(s)
    assert api.scan_allowed(t("2026-11-20 15:00"))          # thứ 6, 15:00
    assert not api.scan_allowed(t("2026-11-20 12:00"))      # giữa phiên
    assert not api.scan_allowed(t("2026-11-21 16:00"))      # thứ 7


def test_backup_restore_roundtrip(tmp_path):
    from app import backup
    conn = connect(tmp_path / "t.db")
    conn.execute("INSERT INTO positions(id,sym,entry_d,entry_px,qty,stop) VALUES (1,'VIX','2026-11-13',13.1,100,11.8)")
    conn.execute("INSERT INTO sales(pos_id,d,px,qty) VALUES (1,'2026-11-18',14,40)"); conn.commit()
    f = backup.backup(conn, tmp_path / "bk")
    conn.execute("DELETE FROM sales"); conn.execute("UPDATE positions SET qty=1"); conn.commit()
    backup.restore(f, conn)
    assert conn.execute("SELECT qty FROM positions").fetchone()[0] == 100
    assert conn.execute("SELECT count(*) FROM sales").fetchone()[0] == 1


def test_scan_skips_day_without_session(monkeypatch):
    """Ngày nghỉ lễ: VNINDEX không có nến hôm nay -> quét thật bỏ qua, không gửi gì."""
    from app import scan
    import datetime as dt
    hom_qua = (dt.datetime.now(dt.timezone(dt.timedelta(hours=7))) - dt.timedelta(days=1)).date().isoformat()
    monkeypatch.setattr(scan, "get_ohlcv", lambda *a, **k: [dict(d=hom_qua, o=1, h=1, l=1, c=1, v=1)])
    monkeypatch.setattr(scan, "connect", lambda: None)
    r = scan.run(dry_run=False)
    assert r["skipped"] and r["n"] == 0


def test_scan_retry_then_warn(monkeypatch):
    """Chưa có nến hôm nay: thử lại RETRIES lần, hết lượt thì gửi 1 tin cảnh báo; có nến thì không cảnh báo."""
    from app import scan
    sent, calls = [], []
    monkeypatch.setattr(scan.time, "sleep", lambda s: None)
    monkeypatch.setattr(scan.notify, "enabled", lambda: True)
    monkeypatch.setattr(scan.notify, "send_text", sent.append)
    log = scan.logging.getLogger("t")
    r = scan.run_with_retry(lambda: calls.append(1) or dict(date="2026-11-23", skipped=True), log)
    assert len(calls) == scan.RETRIES + 1 and len(sent) == 1 and "23/11" in sent[0] and r["skipped"]
    sent.clear(); calls.clear()
    seq = iter([dict(date="2026-11-23", skipped=True), dict(date="2026-11-24", n=700)])
    r = scan.run_with_retry(lambda: next(seq), log)                  # lần 2 đã có nến: quét bình thường
    assert r["n"] == 700 and not sent
