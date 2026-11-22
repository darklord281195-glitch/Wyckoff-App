"""Rủi ro danh mục: rủi ro mở theo cắt lỗ hiện tại, tỷ trọng ngành, cảnh báo ngưỡng; cài đặt vốn qua API."""
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from app import api  # noqa: E402
from app.core.risk import portfolio_risk, DEFAULTS  # noqa: E402
from app.db import connect  # noqa: E402


def pos(id, sym, qty, c, stop, sold=0):
    return dict(id=id, sym=sym, qty=qty, sold=sold, c=c, cur_stop=stop, stop=stop)


def test_open_risk_and_warnings():
    st = dict(DEFAULTS, capital=100.0)                       # 100 triệu
    ps = [pos(1, "AAA", 1000, 20.0, 18.0),                   # rủi ro 1000 × 2.000 đ = 2 triệu
          pos(2, "BBB", 2000, 10.0, 8.5, sold=1000),         # còn 1000 cp × 1.500 đ = 1,5 triệu
          pos(3, "CCC", None, 5.0, 4.0)]                     # chưa nhập số lượng
    r = portfolio_risk(ps, st, {"AAA": "Ngân hàng", "BBB": "Ngân hàng"}, "green")
    assert r["total_risk"] == 3_500_000 and r["heat"] == 3.5 and r["no_qty"] == ["CCC"]
    assert r["sectors"] == [{"name": "Ngân hàng", "value": 30_000_000, "pct": 100.0}]
    assert any("Ngân hàng chiếm 100" in w for w in r["warnings"])          # 1 ngành > 40%
    assert not any("Tổng rủi ro" in w for w in r["warnings"])              # 3,5% < 6%
    r = portfolio_risk(ps, dict(st, max_heat=3), {}, "red")
    assert any("Tổng rủi ro mở 3,5%" in w for w in r["warnings"]) and any("Đèn đỏ" in w for w in r["warnings"])
    assert r["factor"] == 0.0


def test_below_stop_counts_zero_risk_and_warns():
    r = portfolio_risk([pos(1, "AAA", 1000, 9.0, 10.0)], dict(DEFAULTS), {}, "yellow")
    assert r["total_risk"] == 0 and r["factor"] == 0.5 and any("AAA đang dưới cắt lỗ" in w for w in r["warnings"])


def test_settings_api(tmp_path, monkeypatch):
    conn = connect(tmp_path / "t.db")
    monkeypatch.setattr(api, "conn", conn)
    c = TestClient(api.app)
    assert c.get("/api/settings").json()["capital"] == DEFAULTS["capital"]
    got = c.put("/api/settings", json={"capital": 250, "risk_pct": 0.5}).json()
    assert got["capital"] == 250 and got["risk_pct"] == 0.5 and got["max_heat"] == DEFAULTS["max_heat"]
    assert c.put("/api/settings", json={"capital": -1}).status_code == 422
    r = c.get("/api/portfolio/risk").json()
    assert r["capital"] == 250 and r["n"] == 0 and r["warnings"] == []
