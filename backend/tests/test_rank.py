"""Top 10 tiềm năng: chỉ báo, chấm điểm 3 mục, tự doanh, lưu mỗi phiên + thay đổi, tin Telegram, API, kiểm chứng."""
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from app import api, scan, rank_bt  # noqa: E402
from app.core import rank, indicators, mcdx, proprietary  # noqa: E402
from app.db import connect  # noqa: E402

FX = Path(__file__).parent / "fixtures"
SYMS = ["TCH", "DPG", "CTS", "CII", "DIG"]


def _db(tmp_path):
    conn = connect(tmp_path / "t.db")
    for s in ["VNINDEX", *SYMS]:
        conn.executemany("INSERT INTO ohlcv(sym,d,o,h,l,c,v) VALUES (?,?,?,?,?,?,?)",
                         [(s, r["d"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in json.load(open(FX / f"{s}.json"))])
    conn.commit()
    return conn


def _days(conn, sym="VNINDEX"):
    return [r[0] for r in conn.execute("SELECT d FROM ohlcv WHERE sym=? ORDER BY d", (sym,))]


def _bars(cl):
    return [dict(d=f"2026-01-{i:03d}", o=c, h=c * 1.01, l=c * 0.99, c=c, v=1.0) for i, c in enumerate(cl)]


# ------------------------------------------------------------------ chỉ báo
def test_indicators():
    cl = [10 + (i % 7) * 0.3 + i * 0.01 for i in range(120)]
    assert indicators.rsi(cl) == mcdx.rsi_wilder(cl, 14)
    m = indicators.macd([5.0] * 60)
    assert m["macd"][32] is None and m["macd"][-1] == 0 and m["hist"][-1] == 0
    up = _bars([10 + i * 0.1 for i in range(120)])
    ic = indicators.ichimoku(up)
    n = len(up)
    assert len(ic["span_a"]) == n + 26 and up[-1]["c"] > max(ic["span_a"][n - 1], ic["span_b"][n - 1])
    assert ic["tenkan"][-1] > ic["kijun"][-1] and ic["chikou"][0] == up[26]["c"]


# ------------------------------------------------------------------ từng mục
def _r(**kw):
    plan = dict(kind="LPS", entry_lo=10.0, entry_hi=10.5, stop=9.5, rr=3.2, in_zone=True, main_target="T2",
                ready=dict(score=82), targets=[dict(k="T1", price=11.0), dict(k="T2", price=13.0)])
    plan.update(kw.pop("plan", {}))
    r = dict(tag="D-LPS", stage="D", c=10.2, liq=20.0, lh=[], distrib=None, events=[], plan=plan)
    r.update(kw)
    return r


def test_wyckoff_pillar_thresholds_and_penalties():
    w = rank.wyckoff_pillar(_r(), {"LPS": dict(n=10, hit_t1=37.5, avg_r=0.05)})
    pts = {x["key"]: x["pts"] for x in w["items"]}
    assert pts == dict(phase=40, ready=20, zone=15, rr=15, upside=10, plan_stats=0)    # dư địa 13/10,2 = +27%
    assert w["score"] == 100
    st = next(x for x in w["items"] if x["key"] == "plan_stats")
    assert st["tone"] == "info" and "37,5%" in st["text"] and "+0,05" in st["text"]
    w = rank.wyckoff_pillar(_r(lh=[dict(d="x", h=1)], distrib=dict(tag="UTAD")))
    assert w["score"] == 100 - 18
    # B/C + Spring, dưới vùng vào trên cắt lỗ, điểm < 60, lời/lỗ 1,6
    w = rank.wyckoff_pillar(_r(tag="B/C", plan=dict(kind="Spring/Test", test_kind="Spring", in_zone=False,
                                                    ready=dict(score=55), rr=1.6), c=9.8))
    pts = {x["key"]: x["pts"] for x in w["items"]}
    assert pts["phase"] == 30 and pts["ready"] == 4 and pts["zone"] == 10 and pts["rr"] == 5
    # bản quét cũ không có test_kind: lấy sự kiện cuối Spring/ST
    w = rank.wyckoff_pillar(_r(tag="B/C", events=[dict(k="Spring"), dict(k="ST")], plan=dict(kind="Spring/Test")))
    assert w["items"][0]["pts"] == 24
    # không có kế hoạch, kẹp 0
    w = rank.wyckoff_pillar(dict(tag="SOS hỏng", c=5, lh=[1], distrib=dict(tag="SOW"), plan=None))
    assert w["score"] == 0
    assert rank.wyckoff_pillar(dict(tag="dưới hỗ trợ", c=5, plan=dict(kind="Spring/Test")))["items"][0]["pts"] == 12
    assert rank.wyckoff_pillar(dict(tag="dưới hỗ trợ", c=5, plan=None))["items"][0]["pts"] == 8


def test_tech_pillar_and_missing_data():
    t = rank.tech_pillar(_bars([10 + i * 0.05 for i in range(200)]), None)
    keys = [x["key"] for x in t["items"]]
    assert keys == ["rsi", "macd", "mcdx", "ichimoku", "fund"]
    assert all(x["max"] == 20 for x in t["items"]) and 0 <= t["score"] <= 100
    ich = t["items"][3]
    assert ich["pts"] == 20                         # tăng đều: trên mây, Tenkan > Kijun, mây xanh, trên 26 phiên trước
    assert t["items"][4]["pts"] == 10 and t["items"][4]["text"] == "chưa đủ BCTC"
    short = rank.tech_pillar(_bars([10.0] * 50), None)
    assert all(x["pts"] == 10 for x in short["items"]) and short["score"] == 50
    f = rank.fund_part(dict(np_ttm=100, np_growth=20, roe=12, revenue_ttm=2000, debt_equity=0))
    # 2 tốt (lãi, tăng) + 1 TB (ROE) + 1 TB (biên 5%) ; nợ = 0 bỏ qua
    assert f["pts"] == round(20 * 3 / 4, 1)
    assert rank.fund_part(dict(np_ttm=100))["pts"] == 10


def test_flow_pillar():
    f = rank.flow_pillar(10, 20.0, 5.0, dict(net=6.0, net5=1.0))     # 20 tỷ / 200 tỷ = 10% → 50; tự doanh 3% → 50
    assert f["score"] == 100
    f = rank.flow_pillar(10, -200.0, None, dict(net=-100.0, net5=0))
    assert f["score"] == 0
    f = rank.flow_pillar(10, None, None, None)
    assert f["score"] == 50 and all(x["text"] == "chưa có dữ liệu" for x in f["items"])
    s = rank.score_symbol(_r(), _bars([10 + i * 0.05 for i in range(200)]), None, None, None, None)
    assert s["total"] == round((s["pillars"]["wyckoff"]["score"] + s["pillars"]["tech"]["score"] + 50) / 3)
    assert len(s["highlights"]) <= 3 and all(x["tone"] == "good" for x in s["highlights"])
    assert rank.eligible(_r()) and not rank.eligible(_r(plan=dict(stop=None)))


# ------------------------------------------------------------------ tự doanh
def test_prop_net_and_sync(tmp_path):
    conn = _db(tmp_path)
    days = _days(conn, "TCH")
    assert proprietary.prop_net(conn, "TCH", days[-1]) is None                     # chưa tải
    got = [dict(d=d, buy=2.0, sell=1.0) for d in days[-40:-2:2]][::-1]             # cách phiên có giao dịch
    calls = []

    def fake(sym, size=400):
        calls.append(sym)
        if sym == "DPG":
            raise OSError("lỗi")
        return got, days[-3]                                                        # nguồn trễ 2 phiên
    err = proprietary.sync_prop(conn, ["TCH", "DPG"], days[-1], workers=2, fetcher=fake)
    assert err == ["DPG"] and sorted(calls) == ["DPG", "TCH"]
    p = proprietary.prop_net(conn, "TCH", days[-1])
    assert p and p["lag"] == 2 and p["upto"] == days[-3]
    want = sum(1.0 for x in got if days[-22] <= x["d"] <= days[-3])
    assert p["net"] == want
    assert proprietary.prop_net(conn, "TCH", days[-1], max_lag=1) is None
    # đã có tới upto -> không tải lại
    calls.clear()
    proprietary.sync_prop(conn, ["TCH"], days[-3], fetcher=fake)
    assert calls == []
    # n phiên trước ngày nguồn bắt đầu có dữ liệu -> None
    assert proprietary.prop_net(conn, "TCH", days[-1], n=60) is None


# ------------------------------------------------------------------ rank + lưu mỗi phiên
def _scan(conn, monkeypatch, days):
    monkeypatch.setattr(scan, "connect", lambda: conn)
    for d in days:
        scan.run(symbols=SYMS, at=d)


def test_rank_and_daily_changes(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    ds = _days(conn)[-7:]
    _scan(conn, monkeypatch, ds)
    rows = rank.rank(conn, ds[-1], 0, "yellow")
    assert {x["sym"] for x in rows} == set(SYMS)
    pool = [x for x in rows if not x["excluded"]]
    assert rows[:len(pool)] == pool                                               # nhóm bị loại đứng cuối
    assert [x["total"] for x in pool] == sorted((x["total"] for x in pool), reverse=True)
    assert all(0 <= x["total"] <= 100 and len(x["factors"]) == 3 for x in pool)
    assert all(x["total"] is None for x in rows if x["excluded"] and not x["setup"])
    assert all(x["total"] is not None and x["pct_rank"] is None for x in rows if x["excluded"] and x["setup"])
    for x in rows:
        r = json.loads(conn.execute("SELECT data FROM scan_results WHERE date=? AND sym=?", (ds[-1], x["sym"])).fetchone()[0])
        assert x["eligible"] == rank.eligible(r)
        assert x["excluded"] == (r["tag"] in rank.EXCLUDE_TAGS)
        if (x["tag"] or "").startswith("D-LPS") or x["tag"] == "D sớm":
            assert any(w["key"] == "light" for w in x["warnings"])
    assert rank.rank(conn, ds[-1], 10 ** 6) == []

    monkeypatch.setattr(rank, "MIN_LIQ_BIL", 0)                                    # fixture có mã thanh khoản thấp
    for d in ds:
        rank.save_daily(conn, d, None)
    assert conn.execute("SELECT count(DISTINCT date) FROM rank_daily").fetchone()[0] == len(ds)
    assert rank.compare_date(conn, ds[-1], "prev") == ds[-2]
    assert rank.compare_date(conn, ds[-1], "week") == ds[-6]
    assert rank.compare_date(conn, ds[1], "week") == ds[0]                         # không đủ 5 phiên: phiên cũ nhất
    assert rank.compare_date(conn, ds[0], "prev") is None
    pos = rank.positions(conn, ds[-1], 0, False)
    cur = rank.rank(conn, ds[-1], 0)
    assert pos == rank.positions_of(cur, False)
    n_pool = sum(not x["excluded"] for x in cur)
    assert sorted(pos.values()) == list(range(1, n_pool + 1))

    every = [x["sym"] for x in rank.order(cur)]
    if len(every) >= 3:
        prev = {every[-1]: 1, "ZZZ": 2, every[0]: 3}                               # ZZZ: không còn đủ thanh khoản
        dropped = rank.changes(cur, prev, 2)
        assert cur[0]["prev_pos"] == 3 and cur[0]["new"]
        by = {x["sym"]: x for x in dropped}
        assert by[every[-1]]["pos"] == len(every) and by["ZZZ"]["reason"] == "không còn đủ thanh khoản"
    out = [x["sym"] for x in cur if x["excluded"]]
    if out:                                                                        # mã ở nhóm loại rời top: ghi lý do
        assert rank.changes(cur, {out[0]: 1}, 3)[0]["reason"].startswith("nay ở nhóm loại")
    cnt, n = rank.in_top(conn, ds[-1], 2)
    assert n == len(ds) and all(0 <= v <= n for v in cnt.values())
    assert rank.in_top(conn, ds[-1], 2, last=3)[1] == 3


def test_old_formula_in_parallel(tmp_path, monkeypatch):
    """Công thức cũ 3 mục chạy song song: bảng riêng, snapshot riêng, có trong daily_top / API / kiểm chứng."""
    conn = _db(tmp_path)
    ds = _days(conn)[-3:]
    _scan(conn, monkeypatch, ds)
    rows = rank.rank(conn, ds[-1], 0, "red")
    old = rank.view(rows, "old")
    assert len(old) == len(rows) and not any(x["excluded"] for x in old)
    assert [x["total"] for x in old] == sorted((x["ref_total"] for x in rows), reverse=True)
    assert all(any(w["key"] == "light" for w in x["warnings"]) for x in old)
    monkeypatch.setattr(rank, "MIN_LIQ_BIL", 0)
    for d in ds[:-1]:
        rank.save_daily(conn, d, None)
    top = rank.daily_top(conn, ds[-1], None, n=3)
    assert conn.execute("SELECT count(*) FROM rank_daily_ref WHERE date=?", (ds[-1],)).fetchone()[0] == len(rows)
    assert all(x["eligible"] for x in top["old"]["rows"]) and len(top["old"]["rows"]) <= 3
    assert all(x["setup"] for x in top["rows"])
    snap = {s: (su, pool) for s, su, pool in conn.execute("SELECT sym, setup, pool FROM rank_daily WHERE date=?", (ds[-1],))}
    assert all((x["setup"], int(not x["excluded"])) == snap[x["sym"]] for x in rows if x["total"] is not None)
    assert rank.positions(conn, ds[-1], 0, setups=set(rank.SETUPS)) == \
        rank.positions_of(rank.rank(conn, ds[-1], 0), setups=set(rank.SETUPS))
    assert set(top["both"]) <= {x["sym"] for x in top["rows"]} & {x["sym"] for x in top["old"]["rows"]}
    pos = rank.positions(conn, ds[-1], 0, True, formula="old")
    assert pos == rank.positions_of(rank.view(rank.rank(conn, ds[-1], 0), "old"), True)
    assert rank.in_top(conn, ds[-1], 3, formula="old", eligible_only=True)[1] == len(ds)
    # API
    monkeypatch.setattr(api, "conn", conn)
    monkeypatch.setattr(api, "_TOP_CACHE", {})
    c = TestClient(api.app)
    j = c.get(f"/api/top?date={ds[-1]}&min_liq=0&formula=old").json()
    assert j["formula"] == "old" and j["only"] is True and all(x["eligible"] for x in j["rows"])
    assert all(x["total"] == x["ref_total"] for x in j["rows"]) and isinstance(j["both"], list)
    assert c.get(f"/api/top?date={ds[-1]}&min_liq=0").json()["only"] is False
    js = c.get(f"/api/top?date={ds[-1]}&min_liq=0&setup=spring,near,sos,lps,xyz").json()
    assert js["setup"] == ["lps", "near", "sos", "spring"] and all(x["setup"] for x in js["rows"])
    assert set(js["n_setup"]) == set(rank.SETUPS)
    # tin Telegram
    msg = scan.format_message(ds[-1], dict(c=1700, chg=0.1, light="green", text="x"), [], {}, [],
                              top=dict(rows=[dict(sym="A", total=70)], dropped=[], both=["A"],
                                       old=dict(rows=[dict(sym="A", total=80), dict(sym="B", total=75, new=True)])))
    assert "Công thức cũ (3 mục): A 80 · B 75 🆕" in msg and "Cả hai cùng chọn: A" in msg


def test_setups():
    P = lambda **k: dict(plan=dict(**k))
    assert rank.setup_of(dict(tag="D-LPS?")) == ("lps", "D-LPS?")
    assert rank.setup_of(dict(tag="D-SOS"))[0] == rank.setup_of(dict(tag="D sớm"))[0] == "sos"
    assert rank.setup_of(dict(tag="sát trần")) == ("near", "sát trần")
    assert rank.setup_of(dict(tag="B/C", **P(kind="Spring/Test", test_kind="Spring"))) == ("spring", "Spring")
    assert rank.setup_of(dict(tag="B/C", **P(kind="Spring/Test", test_kind="ST")))[1] == "ST (sắp Spring)"
    near_sc = dict(tag="B/C", stage="BC", c=10.3, range=dict(sup=10), plan={})
    assert rank.setup_of(near_sc)[1] == "sát đáy SC (chờ Spring)"
    assert rank.setup_of(dict(near_sc, c=11)) == (None, None) and rank.setup_of(dict(tag="E?")) == (None, None)
    rows = [dict(sym="A", total=50, excluded=False, eligible=True, setup="lps"),
            dict(sym="B", total=70, excluded=True, eligible=True, setup="spring"),
            dict(sym="C", total=90, excluded=False, eligible=False, setup=None)]
    assert [x["sym"] for x in rank.order(rows)] == ["A", "C"]                       # mặc định: bỏ nhóm loại
    assert [x["sym"] for x in rank.order(rows, setups={"lps", "spring"})] == ["B", "A"]   # lọc điểm vào: có cả Spring
    assert rank.pct_scores([dict(dry=1, vol=1, ready=50)], ref=[dict(dry=0.5, vol=2, ready=50)])[0]["dry"] == 0


def test_format_message_top():
    market = dict(c=1700, chg=0.5, light="red", text="x")
    base = scan.format_message("2026-11-27", market, [], {}, [])
    assert base == scan.format_message("2026-11-27", market, [], {}, [], top=None)
    top = dict(rows=[dict(sym="NT2", total=82, new=False), dict(sym="IDC", total=80, new=True)],
               dropped=[dict(sym="VJC")])
    msg = scan.format_message("2026-11-27", market, [], {}, [], top=top)
    assert "🏆 Top 2 tiềm năng" in msg and "(đèn đỏ: chỉ để theo dõi)" in msg
    assert "NT2 82 · IDC 80 🆕" in msg and "Rời top: VJC" in msg and "/top" in msg
    assert "🏆" not in base


# ------------------------------------------------------------------ API
def test_api_top(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    ds = _days(conn)[-3:]
    _scan(conn, monkeypatch, ds)
    monkeypatch.setattr(api, "conn", conn)
    monkeypatch.setattr(api, "_TOP_CACHE", {})
    c = TestClient(api.app)
    j = c.get(f"/api/top?date={ds[-1]}&min_liq=0&all=true&vs=prev&setup=all").json()
    assert j["date"] == ds[-1] and j["compare"] == dict(vs="prev", date=ds[-2])
    assert j["n_liquid"] == len(SYMS)
    assert all({"prev_pos", "new", "in_top", "in_top_of", "pillars", "factors", "total"} <= set(x) for x in j["rows"])
    assert len(j["rows"]) == j["n_pool"] and all(not x["excluded"] for x in j["rows"])
    assert [f["key"] for f in j["factors"]] == ["dry", "vol", "ready"]
    assert c.get("/api/top?date=2026-11-14").status_code == 404
    j2 = c.get(f"/api/top?min_liq=0&n=1&all=false&setup=all").json()
    jd = c.get(f"/api/top?date={ds[-1]}&min_liq=0").json()                       # mặc định công thức mới: 4 điểm vào
    assert jd["setup"] == sorted(rank.SETUPS) and all(x["setup"] for x in jd["rows"])
    assert len(j2["rows"]) <= 1 and all(x["eligible"] for x in j2["rows"])


# ------------------------------------------------------------------ kiểm chứng
def test_factors_and_pct_scores():
    bars = [dict(c=10 + (i % 2) * 0.1, v=100 if i < 70 else 50) for i in range(80)]
    f = rank.factors(dict(plan=dict(ready=dict(score=72))), bars)
    assert f["ready"] == 72 and abs(f["dry"] - 50 / (50 * 10 + 100 * 50) * 60) < 1e-3 and f["vol"] > 0
    assert rank.factors({}, bars[:30]) == dict(dry=None, vol=f["vol"], ready=None)       # dưới 60 nến: chưa tính cung cạn
    raws = [dict(dry=0.5, vol=1.0, ready=80), dict(dry=1.5, vol=3.0, ready=40), dict(dry=None, vol=2.0, ready=None)]
    sc = rank.pct_scores(raws)
    assert sc[0]["dry"] == 75 and sc[1]["dry"] == 25 and sc[2]["dry"] == 50             # thấp là tốt; thiếu = 50
    assert sc[0]["vol"] > sc[2]["vol"] > sc[1]["vol"] and sc[0]["ready"] == 75
    assert sc[0]["total"] > sc[2]["total"] > sc[1]["total"]
    assert rank.pct_scores([dict(dry=1, vol=1, ready=1)] * 2)[0]["total"] == 50          # bằng nhau: hạng trung bình


def test_spearman_and_fwd():
    assert rank_bt.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1
    assert abs(rank_bt.spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1) < 1e-12
    assert rank_bt._ranks([5, 1, 5, 3]) == [3.5, 1, 3.5, 2]
    assert abs(rank_bt.spearman([1, 1, 2, 3], [1, 2, 3, 4]) - 0.9486832980505138) < 1e-9
    assert rank_bt.spearman([1, 1, 1], [1, 2, 3]) is None
    R = [dict(o=10, c=10)] * 3 + [dict(o=11, c=12), dict(o=12, c=13.2)]
    assert rank_bt.fwd(R, 2, 2) == 20.0 and rank_bt.fwd(R, 3, 5) is None


def test_rank_bt_small_run_and_daily(tmp_path, monkeypatch, capsys):
    conn = _db(tmp_path)
    monkeypatch.setattr(rank_bt, "connect", lambda: conn)
    monkeypatch.setattr(rank_bt, "MIN_LIQ_BIL", 0)
    monkeypatch.setattr(rank_bt, "LOG_DIR", tmp_path)                            # không ghi đè logs thật
    picks, vni = rank_bt.collect(conn, SYMS, "2025-06-01", "2026-09-30", 20)
    assert picks and all({"date", "sym", "tag", "excluded", "dry", "vol", "ready", "fwd20", "fwd60", "eligible"} <= set(x)
                         for x in picks)
    ms = rank_bt.months(picks, vni, 2)
    scored = [x for x in picks if "total" in x]
    assert scored and all(not x["excluded"] and 0 <= x["total"] <= 100 for x in scored)
    res_old = rank_bt.summarize(rank_bt.months(picks, vni, 2, "old"), 2, 20)
    assert "Tất cả" in res_old and all(x["eligible"] for x in picks if x["top_ref"])
    res = rank_bt.summarize(ms, 2, 20)
    assert "Tất cả" in res and set(rank_bt.COLS) <= set(res["Tất cả"])
    monkeypatch.setattr("sys.argv", ["rank_bt", "--symbols", ",".join(SYMS), "--from", "2026-01-01", "--to", "2026-06-30"])
    rank_bt.main()
    assert "Tất cả" in capsys.readouterr().out
    assert not conn.execute("SELECT 1 FROM rank_bt").fetchone()                  # --symbols: không ghi bảng
    # --daily
    monkeypatch.setattr(scan, "connect", lambda: conn)
    ds = _days(conn)[-2:]
    for d in ds:
        scan.run(symbols=SYMS, at=d)
    monkeypatch.setattr(rank, "MIN_LIQ_BIL", 0)
    monkeypatch.setattr("sys.argv", ["rank_bt", "--daily"])
    rank_bt.main()
    assert conn.execute("SELECT count(DISTINCT date) FROM rank_daily").fetchone()[0] == 2
