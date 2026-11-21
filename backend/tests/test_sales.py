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
