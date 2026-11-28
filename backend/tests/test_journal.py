"""Nhật ký: R thật vs R theo luật, cờ cắt lỗ trễ / bán sớm / mua ngoài vùng / đèn đỏ."""
from app.core import journal as J


def bars(closes, start=1):
    return [dict(d=f"2026-03-{start + i:02d}", o=c, h=c, l=c, c=c, v=1) for i, c in enumerate(closes)]


def pos(**kw):
    p = dict(id=1, sym="AAA", kind="LPS", entry_d="2026-03-01", entry_px=10.0, stop=9.0, stop0=9.0,
             qty=1000, targets=[12.0, 13.0], status="closed")
    p.update(kw)
    return p


GOOD_PLAN = (dict(entry_lo=9.8, entry_hi=10.1, rr=2.5), "green")


def run(p, sales, closes, plan=GOOD_PLAN):
    return J.build([p], {p["id"]: sales}, lambda s, d: bars(closes), lambda s, d: plan, 0.02)


def test_late_stop_flag_and_r():
    # luật: đóng cửa 8,8 < 9 ở phiên 4 -> bán phiên 5 giá mở cửa 8,7. Người dùng giữ tới phiên 9 rồi bán 8,0
    closes = [10, 10, 9.5, 8.8, 8.7, 8.5, 8.4, 8.2, 8.0]
    out = run(pos(), [dict(d="2026-03-09", px=8.0, qty=1000)], closes)
    x = out["items"][0]
    assert "cắt lỗ trễ" in x["flags"] and x["r_real"] < x["r_rule"] < 0
    assert out["summary"]["n"] == 1 and out["summary"]["r_lost"] == x["diff"] < 0


def test_early_sale_and_entry_flags():
    closes = [10, 10.5, 11, 11.2, 11.5]
    out = run(pos(entry_px=10.5), [dict(d="2026-03-03", px=11.0, qty=1000)], closes,
              (dict(entry_lo=9.8, entry_hi=10.1, rr=1.5), "red"))
    f = out["items"][0]["flags"]
    assert {"bán sớm trước tín hiệu bán", "mua cao hơn vùng vào", "mua khi đèn đỏ", "lời/lỗ kế hoạch < 2"} <= set(f)


def test_disciplined_trade_has_no_flags_and_open_counts_unrealized():
    closes = [10, 10.4, 10.8, 12.1, 12.5, 13.2]                # chạm T1 phiên 4, T2 phiên 6
    out = run(pos(), [dict(d="2026-03-04", px=12.0, qty=333), dict(d="2026-03-06", px=13.0, qty=667)], closes)
    x = out["items"][0]
    assert x["flags"] == [] and x["r_real"] > 2
    op = run(pos(status="open", stop0=None), [], [10, 10.5, 11])  # đang mở: tính theo giá hiện tại; stop0 trống dùng stop
    assert op["items"][0]["r_real"] > 0 and op["summary"]["open"] == 1 and op["summary"]["n"] == 0


def test_lessons_explain_mistakes_and_fixes():
    # mua đuổi + đèn đỏ + lời/lỗ < 2 + bán sớm; phiên mua chưa đạt kịch bản (lý do từ checklist)
    closes = [10, 10.5, 11, 11.2, 11.5]
    plan = (dict(entry_lo=9.8, entry_hi=10.1, rr=1.5), "red", ["giá ở nửa dưới biên độ phiên"])
    x = run(pos(entry_px=10.5), [dict(d="2026-03-03", px=11.0, qty=1000)], closes, plan)["items"][0]
    titles = [l["title"] for l in x["lessons"] if not l["ok"]]
    assert titles == ["Mua đuổi, cao hơn vùng mua", "Mua khi đèn thị trường đỏ", "Kế hoạch lời/lỗ dưới 2",
                      "Phiên mua chưa đạt kịch bản mua đẹp", "Cắt lỗ quá xa", "Bán sớm khi chưa có tín hiệu bán"]
    assert all(l["fix"] for l in x["lessons"] if not l["ok"]) and "cao hơn cận trên 4,0%" in x["lessons"][0]["detail"]
    # lệnh kỷ luật: chỉ có điểm làm tốt
    closes = [10, 10.5, 11, 11.5, 12.1, 12.5, 13.2]
    ok = J.build([pos(stop=9.4, stop0=9.4)], {1: [dict(d="2026-03-07", px=13.2, qty=1000)]}, lambda s, d: bars(closes), lambda s, d: GOOD_PLAN, 0.02,
                 dict(capital=100.0, risk_pct=1.0))["items"][0]["lessons"]
    assert all(l["ok"] for l in ok) and [l["title"] for l in ok][0] == "Mua trong vùng mua"
