"""REST API cho web Next.js.  Chạy: .venv\\Scripts\\uvicorn app.api:app --port 8000"""
import json, threading, time, datetime as dt
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .db import connect
from .config import LOG_DIR, MIN_LIQ_BIL
from .core.data import get_ohlcv, fetch_remote, add_atc
from .core.wyckoff import analyse, trim, ANALYSIS_DAYS
from .core.market import traffic_light
from .core.positions import simulate
from .core.foreign import get_foreign, MAX_SESSIONS as FX_MAX
from .core.proprietary import get_prop
from .core import rank as rank_mod
from .core import risk as risk_mod
from .core import journal as journal_mod
from .core import forward as forward_mod
from .core import fundamentals as fund
from .core import flow as flow_mod
from .core import paper as paper_mod
from .core import mcdx as mcdx_mod
from .universe import GROUP_NAMES, INDEX, group_of, watchlist, listing, sectors
from . import scan as scan_mod
from . import intraday as intraday_mod
from . import health as health_mod
from .core.signals import PRIORITY
from .backtest import BUY_FEE, SELL_FEE

app = FastAPI(title="Wyckoff Scanner")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])
class _ThreadConn:
    """Mỗi luồng một kết nối SQLite. FastAPI chạy các endpoint đồng bộ song song trong thread pool; một đối tượng
    sqlite3.Connection dùng chung nhiều luồng thỉnh thoảng trả kết quả sai (vd fetchone() = None) -> lỗi 500, mà lỗi 500
    không có header CORS nên trình duyệt chỉ báo "Failed to fetch" (trang Tổng quan gọi nhiều API cùng lúc)."""

    def __init__(self):
        self._local = threading.local()
        self._local.conn = connect()             # luồng khởi động: tạo bảng / nâng cấp DB một lần

    def _get(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = connect(init=False)
        return c

    def __getattr__(self, name):
        return getattr(self._get(), name)


conn = _ThreadConn()
_lock = threading.Lock()
_scan_state = {"running": False, "last": None}


def _session(date: str | None = None):
    """Phiên đã quét: `date` nếu có trong DB (không có thì 404), mặc định phiên mới nhất."""
    if not date:
        return conn.execute("SELECT max(date) FROM scan_results").fetchone()[0]
    if not conn.execute("SELECT 1 FROM scan_results WHERE date=? LIMIT 1", (date,)).fetchone():
        raise HTTPException(404, f"Chưa có kết quả quét phiên {date}")
    return date


@app.get("/api/scan/dates")
def scan_dates():
    return [r[0] for r in conn.execute("SELECT DISTINCT date FROM scan_results ORDER BY date DESC")]


def _fundamentals(code: str, at: str | None):
    """Chỉ số cơ bản tại ngày xem (chỉ báo cáo đã công bố tới ngày đó) + P/E mới nhất (khi xem phiên mới nhất).
    Chưa có BCTC thì tải ngay; lỗi mạng thì trả phần đã có."""
    err = None
    try:
        fund.sync(conn, [code])
    except Exception as e:
        err = str(e)
    m = fund.metrics_at(fund.load(conn, code), at)
    pe = None
    if not at:
        meta = conn.execute("SELECT pe, mcap, pe_date FROM fin_meta WHERE sym=?", (code,)).fetchone()
        today = dt.date.today().isoformat()
        if meta and meta["pe_date"] == today:
            pe = dict(pe=meta["pe"], mcap=meta["mcap"])
        else:
            try:
                pe = fund.fetch_pe(code)
                conn.execute("INSERT INTO fin_meta(sym, pe, mcap, pe_date) VALUES (?,?,?,?) ON CONFLICT(sym) DO UPDATE "
                             "SET pe=excluded.pe, mcap=excluded.mcap, pe_date=excluded.pe_date",
                             (code, pe["pe"], pe["mcap"], today))
                conn.commit()
            except Exception as e:
                err = err or str(e)
    out = dict(m or {}, pe=pe and pe["pe"], mcap=pe and pe["mcap"], error=err) if (m or pe) else (dict(error=err) if err else None)
    if out and m:                                 # trung vị ngành (ICB) để so sánh trên thẻ Cơ bản
        lst = listing(conn)
        icb = (lst.get(code) or {}).get("icb")
        if icb:
            peers = [s for s, v in lst.items() if v.get("icb") == icb and s != code]
            key = (icb, at or dt.date.today().isoformat(), m.get("fiscal"))
            if key not in _PEER_CACHE:
                _PEER_CACHE[key] = fund.peer_medians(conn, peers, m.get("fiscal"), at)
            out["sector"] = dict(name=(lst.get(code) or {}).get("icb_name"), **_PEER_CACHE[key]) if _PEER_CACHE[key] else None
    return out


_PEER_CACHE: dict = {}            # (ngành, ngày, quý) -> trung vị ngành; tính lại mỗi ngày


@app.get("/api/flow")
def flow(short: int = Query(5, ge=1, le=60), long: int = Query(20, ge=5, le=120), end: str | None = None):
    """Dòng tiền theo ngành: tỷ trọng giá trị giao dịch kỳ gần (short phiên) so với kỳ trước (long phiên)."""
    return flow_mod.sector_flow(conn, short, long, end)


@app.get("/api/forward")
def forward(live: int = 1):
    """Chấm điểm tín hiệu mua đã báo theo luật backtest; live=1 chỉ tín hiệu báo thật (bỏ phiên tạo lại)."""
    return forward_mod.score(conn, live_only=bool(live))


@app.get("/api/backtest/portfolio")
def backtest_portfolio():
    """Lần chạy backtest danh mục mới nhất (python -m app.backtest --portfolio); None nếu chưa chạy."""
    r = conn.execute("SELECT created, params, metrics, curves FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    return dict(created=r["created"], params=json.loads(r["params"]), metrics=json.loads(r["metrics"]),
                curves=json.loads(r["curves"]))


@app.get("/api/sectors")
def sectors_get(date: str | None = None):
    """Sức mạnh ngành tại phiên quét (mặc định mới nhất), xếp theo RS20 giảm dần."""
    d = _session(date)
    rows = [dict(r) for r in conn.execute(
        "SELECT icb, name, n, rs20, rs60, pct_d, fx10 FROM sector_stats WHERE date=? ORDER BY rs20 DESC", (d,))]
    return dict(date=d, rows=rows)


@app.get("/api/market")
def market(date: str | None = None):
    d = _session(date)
    row = conn.execute("SELECT data FROM scan_results WHERE sym=? AND date=?", (INDEX, d)).fetchone() if d else None
    res = json.loads(row[0]) if row else None
    return dict(date=d, **traffic_light(res, res and res.get("breadth")), tag=res and res.get("tag"))


_MCDX_CACHE: dict[str, dict] = {}


def _mcdx_fallback(d: str, syms: list[str]) -> dict:
    """MCDX của mọi mã tại phiên d, tính từ giá đóng cửa trong DB, cho bản quét cũ chưa có trường `mcdx`.
    Cùng dữ liệu như scan.py (giá 500 ngày tính tới hôm nay, cắt tới phiên d). Một truy vấn, nhớ theo phiên."""
    if d in _MCDX_CACHE:
        return _MCDX_CACHE[d]
    since = (dt.date.today() - dt.timedelta(days=500)).isoformat()
    q = "SELECT c FROM ohlcv WHERE sym=? AND d>=? AND d<=? ORDER BY d"          # theo khóa chính (sym, d): nhanh
    out = {s: mcdx_mod.last([r[0] for r in conn.execute(q, (s, since, d))]) for s in syms}
    _MCDX_CACHE.clear(); _MCDX_CACHE[d] = out          # chỉ giữ một phiên
    return out


@app.get("/api/scan/latest")
def scan_latest(group: str | None = None, date: str | None = None):
    d = _session(date)
    if not d:
        return dict(date=None, rows=[])
    wl = set(watchlist(conn))
    lst = listing(conn)
    rows = []
    found = conn.execute("SELECT sym, data FROM scan_results WHERE date=? AND sym<>?", (d, INDEX)).fetchall()
    scan_syms = [x[0] for x in found]
    for sym, data in found:
        r = json.loads(data)
        if "mcdx" not in r:                              # bản quét trước khi có MCDX: tính bổ sung
            r["mcdx"] = _mcdx_fallback(d, scan_syms).get(sym)
        gs = group_of(sym, lst) + (["wl"] if sym in wl else [])
        if group and group not in gs:
            continue
        info = lst.get(sym, {})
        p = r.get("plan") or {}
        rows.append(dict(sym=sym, groups=gs, floor=info.get("floor"), name=info.get("name"),
                         ready=(p.get("ready") or {}).get("score"), rr=p.get("rr"), plan_kind=p.get("kind"),
                         entry_lo=p.get("entry_lo"), entry_hi=p.get("entry_hi"), stop=p.get("stop"),
                         in_zone=p.get("in_zone"),
                         # Spring/ST trong 15 phiên gần nhất (kế hoạch Spring/Test); bản quét cũ chưa có test_kind thì lấy sự kiện cuối
                         test=(p.get("test_kind") or next((e["k"] for e in reversed(r.get("events", [])) if e["k"] in ("Spring", "ST")), None))
                         if p.get("kind") == "Spring/Test" else None,
                         # % giá so với đáy SC, chỉ khi còn trong/quanh vùng tích lũy (chưa SOS)
                         sc=round((r["c"] / r["range"]["sup"] - 1) * 100, 1)
                         if r.get("range") and r["stage"] in ("BC", "below", "near") else None,
                         vx=r.get("vx"),
                         tag=r["tag"], stage=r["stage"], c=r["c"], chg=r["chg"],
                         liq=r["liq"], rs5=r.get("rs5"), rs20=r.get("rs20"), rs60=r.get("rs60"),
                         dist=r.get("dist"), extra=r.get("extra"), weak_drop=r.get("weak_drop"),
                         levels=r.get("levels"), pos52=r.get("pos52"), fx10=r.get("fx10"),
                         banker=(r.get("mcdx") or {}).get("banker"), banker_chg5=(r.get("mcdx") or {}).get("banker_chg5"),
                         banker_label=(r.get("mcdx") or {}).get("label"), banker_tone=(r.get("mcdx") or {}).get("tone")))
    return dict(date=d, rows=rows, groups=GROUP_NAMES, sectors=sectors(conn))


_TOP_CACHE: dict = {}             # (phiên, GT tối thiểu) -> (thời điểm, các dòng rank()); hết hạn sau TOP_TTL giây
TOP_TTL = 600


def _top_rows(d: str, min_liq: float, light: str | None, fresh: bool = False) -> list[dict]:
    """Bảng xếp hạng phiên d (mọi mã GT ≥ min_liq), nhớ TOP_TTL giây."""
    hit = _TOP_CACHE.get((d, min_liq))
    if hit and not fresh and time.time() - hit[0] < TOP_TTL:
        return hit[1]
    rows = rank_mod.rank(conn, d, min_liq, light)
    _TOP_CACHE[(d, min_liq)] = (time.time(), rows)
    return rows


def _validation(table: str = "rank_bt"):
    """Kết quả kiểm chứng lịch sử (python -m app.rank_bt) theo giai đoạn; None nếu chưa chạy."""
    try:
        rows = [dict(x) for x in conn.execute(f"SELECT * FROM {table} ORDER BY CASE period WHEN 'Tất cả' THEN 9 ELSE 0 END, period")]
    except Exception:                            # DB cũ chưa có bảng
        return None
    return dict(rows=rows, updated=max(x["updated"] or "" for x in rows)) if rows else None


@app.get("/api/top")
def top(date: str | None = None, min_liq: float = Query(MIN_LIQ_BIL, ge=0), n: int = Query(10, ge=1, le=50),
        all: bool | None = None, vs: str = Query("prev", pattern="^(prev|week)$"),
        formula: str = Query("new", pattern="^(new|old)$"), setup: str = ""):
    """Top n tiềm năng phiên `date` (mặc định mới nhất). formula='new': điểm = TB phần trăm cung cạn · biến động thấp ·
    điểm sẵn sàng trong nhóm được xếp (bỏ B/C, SOS hỏng, dưới hỗ trợ); 'old': công thức cũ 3 mục (chạy song song để so).
    all=false: chỉ mã có điểm mua (mặc định: new = mọi mã, old = chỉ mã có điểm mua). vs: so thứ hạng với phiên trước
    (prev) hoặc 1 tuần trước (week). both = mã nằm trong top n của cả hai công thức (mỗi công thức theo mặc định).
    setup: lọc điểm vào đẹp, danh sách khóa cách nhau dấu phẩy trong rank.SETUPS (spring, near, sos, lps); rỗng = mọi mã."""
    setups = {s for s in setup.split(",") if s in rank_mod.SETUPS} or None
    d = _session(date)
    if not d:
        raise HTTPException(404, "Chưa có kết quả quét")
    mk = market(d)
    base = _top_rows(d, min_liq, mk["light"])
    rows = [dict(x) for x in rank_mod.view(base, formula)]                # changes() gắn thêm trường: không sửa bản trong cache
    only = (formula == "old") if all is None else not all
    other = rank_mod.order(rank_mod.view(base, "new" if formula == "old" else "old"), formula == "new", setups)[:n]
    cmp = rank_mod.compare_date(conn, d, vs)
    prev_pos = {}
    if cmp:
        if setups:                                  # snapshot không lưu loại điểm vào: chấm lại phiên so sánh (có cache)
            prev_pos = rank_mod.positions_of(rank_mod.view(_top_rows(cmp, min_liq, market(cmp)["light"]), formula),
                                             only, setups)
        else:
            snap = min_liq == MIN_LIQ_BIL and conn.execute("SELECT 1 FROM rank_daily WHERE date=? LIMIT 1", (cmp,)).fetchone()
            prev_pos = rank_mod.positions(conn, cmp, min_liq, only,
                                          rows=None if snap else _top_rows(cmp, min_liq, market(cmp)["light"]), formula=formula)
    dropped = rank_mod.changes(rows, prev_pos, n, only, setups)
    cnt, days = rank_mod.in_top(conn, d, n, formula=formula, eligible_only=only) if not setups else ({}, 0)
    out = [dict(x, in_top=cnt.get(x["sym"], 0), in_top_of=days) for x in rank_mod.order(rows, only, setups)[:n]]
    others = {x["sym"] for x in other}
    return dict(date=d, light=mk["light"], light_text=mk.get("text"), min_liq=min_liq,
                factors=[dict(key=k, label=lb) for k, lb, _ in rank_mod.FACTORS], exclude=list(rank_mod.EXCLUDE_TAGS),
                n_liquid=len(rows), n_pool=sum(not x["excluded"] for x in rows),
                n_eligible=sum(x["eligible"] and not x["excluded"] for x in rows), compare=dict(vs=vs, date=cmp),
                formula=formula, only=only, both=[x["sym"] for x in out if x["sym"] in others],
                setups=dict(rank_mod.SETUPS), setup=sorted(setups or []),
                n_setup={k: sum(x.get("setup") == k and x["total"] is not None for x in rows) for k in rank_mod.SETUPS},
                rows=out, dropped=dropped, validation=_validation("rank_bt_ref" if formula == "old" else "rank_bt"))


@app.get("/api/signals")
def signals(days: int = 30, sym: str | None = None, until: str | None = None):
    """Tín hiệu `days` ngày tính lùi từ phiên `until` (mặc định phiên mới nhất)."""
    end = until or conn.execute("SELECT max(date) FROM signals").fetchone()[0]
    q = "SELECT date, sym, kind, is_new, text FROM signals WHERE date >= date(?, ?) AND date <= ?"
    args = [end, f"-{days} day", end]
    if sym:
        q += " AND sym=?"; args.append(sym.upper())
    order = " ".join(f"WHEN '{k}' THEN {p}" for k, p in PRIORITY.items())
    return [dict(r) for r in conn.execute(q + f" ORDER BY date DESC, CASE kind {order} ELSE 99 END, sym", args)]


MIN_LOOKBACK = 60                  # khoảng tự chọn ngắn hơn thì nới ra (distribution cần ≥ 60 phiên)


def _analysis(code: str, at: str | None = None, start: str | None = None):
    """(R, analyse) của mã tại phiên `at` (mặc định phiên mới nhất), chỉ dùng dữ liệu tới phiên đó.
    start: chỉ dò vùng Wyckoff trong các phiên từ `start` tới `at` (khoảng người dùng chọn trên biểu đồ).
    Mã cổ phiếu VN có 3 ký tự; dài hơn là chỉ số (VNINDEX, VN30...) nên không làm tròn bước giá."""
    today = dt.date.fromisoformat(at) if at else dt.date.today()
    days = max(ANALYSIS_DAYS, (today - dt.date.fromisoformat(start)).days + 30) if start else ANALYSIS_DAYS
    span = max(1000, (dt.date.today() - today).days + days + 30)      # đủ lịch sử để cắt tới `at`
    try:
        IDX = get_ohlcv(conn, INDEX, span, refresh=False)
        R = get_ohlcv(conn, code, span, refresh=not conn.execute(
            "SELECT 1 FROM ohlcv WHERE sym=? LIMIT 1", (code,)).fetchone())
    except Exception as e:
        raise HTTPException(502, str(e))
    if at:
        R = [r for r in R if r["d"] <= at]; IDX = [r for r in IDX if r["d"] <= at]
    R, IDX = trim(R, days, today), trim(IDX, days, today)
    if not R:
        raise HTTPException(404, f"Không có dữ liệu {code}" + (f" tới ngày {at}" if at else ""))
    floor = None if len(code) > 3 else (listing(conn).get(code) or {}).get("floor") or "UPCOM"
    lookback = max(MIN_LOOKBACK, sum(r["d"] >= start for r in R)) if start else 190
    return R, analyse(R, IDX if code != INDEX else None, floor, lookback, keep_distrib=bool(start))


@app.get("/api/listing")
def listing_get():
    """Danh sách mã cho ô tìm kiếm: [{sym, name, floor}], kèm VNINDEX."""
    rows = [dict(sym=s, name=v.get("name"), floor=v.get("floor")) for s, v in sorted(listing(conn).items())]
    return [dict(sym=INDEX, name="Chỉ số VN-Index", floor="HOSE")] + rows


def _fx_sessions(code: str, at: str | None, res: dict | None) -> int:
    """Số phiên khối ngoại cần cho trang mã: tối thiểu MAX_SESSIONS, dài hơn nếu vùng Wyckoff bắt đầu sớm hơn (nút "Theo vùng")."""
    start = ((res or {}).get("range") or {}).get("start")
    if not start:
        return FX_MAX
    q = "SELECT count(*) FROM ohlcv WHERE sym=? AND d>=?" + (" AND d<=?" if at else "")
    n = conn.execute(q, (code, start, at) if at else (code, start)).fetchone()[0]
    return max(FX_MAX, n + 5)


@app.get("/api/symbols/{code}")
def symbol(code: str, at: dt.date | None = None, start: dt.date | None = Query(None, alias="from")):
    """Phân tích tại phiên `at` (chỉ dữ liệu tới đó; có `from` thì chỉ dò vùng trong khoảng from–at).
    Biểu đồ nhận toàn bộ lịch sử ngày, kể cả sau `at`, để so với diễn biến thực tế (frontend gộp nến tuần)."""
    code = code.upper()
    at, start = at and at.isoformat(), start and start.isoformat()
    if start and at and start >= at:
        raise HTTPException(400, "Ngày bắt đầu phải trước ngày kết thúc")
    R, res = _analysis(code, at, start)
    full = get_ohlcv(conn, code, 10000, refresh=False)
    n_fx = _fx_sessions(code, at, res)
    fx, fx_err = get_foreign(conn, code, at, n_fx) if len(code) == 3 else ([], None)   # khối ngoại, tự doanh: chỉ cổ phiếu
    prop, prop_err = get_prop(conn, code, at, n_fx) if len(code) == 3 else ([], None)
    fundamentals = _fundamentals(code, at) if len(code) == 3 else None
    kind = ((res or {}).get("plan") or {}).get("kind")
    st = kind and conn.execute("SELECT * FROM backtest_stats WHERE plan=?", (kind.split(" (")[0],)).fetchone()
    try:
        light = market(at)["light"]          # đèn của phiên đang xem (phiên quét gần nhất nếu không có `at`)
    except HTTPException:
        light = None
    sc = [dict(x) for x in conn.execute("SELECT * FROM scenario_stats WHERE plan=?", (kind.split(" (")[0],))] if kind else []
    lst = listing(conn)
    info = lst.get(code, {})
    return dict(sym=code, groups=group_of(code, lst), name=info.get("name"), floor=info.get("floor"),
                sector=info.get("icb_name"), unit="pt" if len(code) > 3 else "k",    # VNM, VND... là cổ phiếu
                ohlcv=full,
                analysis=res, signals=signals(120, code, at), at=at, start=start, foreign=fx, foreign_error=fx_err, proprietary=prop, proprietary_error=prop_err, plan_stats=dict(st) if st else None,
                scenario_stats=dict(light=light, rows=sc), fundamentals=fundamentals, in_watchlist=code in watchlist(conn))


@app.get("/api/health")
def health_get():
    """Sức khỏe hệ thống: từng mục (quét, dữ liệu, lỗi tải, nguồn dự phòng, task Windows, sao lưu...) và mức tệ nhất."""
    return health_mod.status(conn)


@app.get("/api/symbols/{code}/check")
def symbol_check(code: str):
    """Bảng kiểm tra trước khi mua (14h15–14h29): từng điều kiện kịch bản mua đẹp theo nến đang chạy, kết luận,
    khối lượng gợi ý theo vốn / % rủi ro / đèn và tổng rủi ro danh mục sau khi mua."""
    try:
        out = intraday_mod.live_check(conn, code)
    except Exception as e:                       # lỗi mạng / thiếu dữ liệu: báo rõ, không làm hỏng trang mã
        raise HTTPException(502, str(e))
    pr = _portfolio_risk()
    out["size"] = risk_mod.size_for(risk_mod.get_settings(conn), out["light"], out["price"], out["stop"], pr["heat"])
    out["positions"] = dict(n=pr["n"], max_pos=pr["max_pos"])
    return out


@app.get("/api/symbols/{code}/hourly")
def hourly(code: str):
    """Nến 1 giờ ~1 năm gần nhất, tải thẳng từ VNDirect mỗi lần xem (không lưu DB); nến cuối ngày gồm cả ATC."""
    try:
        sym = code.upper()
        return add_atc(fetch_remote(sym, 365, retries=2, res="60"), fetch_remote(sym, 370, retries=2))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


class WatchItem(BaseModel):
    sym: str
    note: str | None = None


@app.get("/api/watchlist")
def wl_get():
    """Watchlist; held = đang có lệnh mở trong Danh mục (tính lúc đọc, không lưu thành ghi chú)."""
    held = {r[0] for r in conn.execute("SELECT DISTINCT sym FROM positions WHERE status='open'")}
    return [dict(r, held=r["sym"] in held) for r in conn.execute("SELECT sym, note, added FROM watchlist ORDER BY sym")]


@app.post("/api/watchlist")
def wl_add(item: WatchItem):
    conn.execute("INSERT OR REPLACE INTO watchlist(sym, note) VALUES (?, ?)", (item.sym.upper(), item.note))
    conn.commit()
    return wl_get()


@app.delete("/api/watchlist/{sym}")
def wl_del(sym: str):
    conn.execute("DELETE FROM watchlist WHERE sym=?", (sym.upper(),)); conn.commit()
    return wl_get()


class PositionIn(BaseModel):
    sym: str
    entry_px: float | None = None        # nghìn đồng; mặc định giá đóng cửa phiên mua
    entry_d: dt.date | None = None       # mặc định phiên mới nhất; ngày cũ thì kế hoạch tính tại ngày đó
    qty: int | None = None
    stop: float | None = None            # mặc định theo kế hoạch tại phiên mua
    targets: list[float] | None = None
    note: str | None = None


class SellIn(BaseModel):
    qty: int | None = Field(None, gt=0)  # mặc định bán hết phần còn giữ
    px: float | None = Field(None, gt=0) # nghìn đồng; mặc định giá đóng cửa mới nhất
    d: dt.date | None = None             # mặc định phiên mới nhất


@app.get("/api/positions")
def pos_list():
    """Lệnh đang giữ, kèm trạng thái theo luật bán (cắt lỗ hiện tại, mục tiêu kế tiếp, việc cần làm)."""
    return risk_mod.open_positions(conn)


class SettingsIn(BaseModel):
    capital: float | None = Field(None, gt=0)
    risk_pct: float | None = Field(None, gt=0, le=10)
    max_heat: float | None = Field(None, gt=0, le=100)
    max_pos: int | None = Field(None, gt=0)
    max_sector: float | None = Field(None, gt=0, le=100)


@app.get("/api/settings")
def settings_get():
    return risk_mod.get_settings(conn)


@app.put("/api/settings")
def settings_put(item: SettingsIn):
    return risk_mod.put_settings(conn, item.model_dump(exclude_none=True))


def _portfolio_risk():
    lst = listing(conn)
    return risk_mod.portfolio_risk(risk_mod.open_positions(conn), risk_mod.get_settings(conn),
                                   {s: (v.get("icb_name") or "") for s, v in lst.items()}, market()["light"])


def _light_at(d: str) -> str | None:
    """Đèn thị trường của phiên d: lấy từ kết quả quét nếu có, không thì tính theo xu hướng VNINDEX tới phiên đó."""
    row = conn.execute("SELECT data FROM scan_results WHERE sym=? AND date=?", (INDEX, d)).fetchone()
    res = json.loads(row[0]) if row else None
    if res is None:
        try:
            _, res = _analysis(INDEX, d)
        except HTTPException:
            return None
    return traffic_light(res, res and res.get("breadth"))["light"]


@app.get("/api/journal")
def journal():
    """Nhật ký: R thật vs R theo luật cho từng lệnh, cờ vi phạm lúc mua/bán, tổng hợp so với backtest."""
    def bars_of(sym, d):
        return [r for r in get_ohlcv(conn, sym, 10000, refresh=False) if r["d"] >= d]

    def plan_at(sym, d):
        """(kế hoạch, đèn, lý do phiên mua chưa đạt kịch bản mua đẹp theo nến cả ngày) tại ngày mua."""
        try:
            R, a = _analysis(sym, d)
        except HTTPException:
            return {}, _light_at(d), []
        plan = (a or {}).get("plan") or {}
        items = intraday_mod.checklist(plan, R, ((a or {}).get("range") or {}).get("res"), full_day=True) if len(R) > 21 else []
        fails = [x["why"] for x in items if x["ok"] is False and not x.get("advisory")
                 and x["key"] not in ("plan", "zone", "rr")]   # 3 mục này đã có riêng; MCDX chỉ tham khảo
        return plan, _light_at(d), fails

    bt = conn.execute("SELECT avg_r FROM backtest_stats WHERE plan='Tất cả'").fetchone()
    return journal_mod.build(journal_mod.all_positions(conn), journal_mod.sales_by_position(conn), bars_of, plan_at,
                             bt[0] if bt else None, risk_mod.get_settings(conn))


@app.get("/api/intraday")
def intraday(date: str | None = None):
    """Cảnh báo trong phiên của một ngày (mặc định hôm nay): mua thử nghiệm 14h10 (buy) và cảnh báo giá."""
    d = date or dt.datetime.now(VN_TZ).date().isoformat()
    return [dict(r) for r in conn.execute(
        "SELECT date, sym, kind, text, at FROM intraday_alerts WHERE date=? ORDER BY at DESC, sym", (d,))]


@app.get("/api/paper")
def paper_get():
    """Sổ lệnh thử nghiệm: từng lệnh app tự mua + kết quả theo luật bán, tổng hợp theo nhóm điều kiện."""
    return paper_mod.score(conn)


@app.get("/api/paper/review")
def paper_review():
    """Bản xem lại sổ thử nghiệm mới nhất (scripts/weekly-review): tóm tắt + báo cáo đầy đủ (markdown)."""
    files = sorted(LOG_DIR.glob("review-2*.md"))
    if not files:
        return None
    tg = LOG_DIR / "review-telegram.txt"
    return dict(date=files[-1].stem[7:], report=files[-1].read_text(encoding="utf-8"),
                summary=tg.read_text(encoding="utf-8") if tg.exists() else None)


@app.get("/api/portfolio/risk")
def portfolio_risk():
    """Tổng rủi ro mở (% vốn), số lệnh, tỷ trọng ngành, cảnh báo vượt ngưỡng; factor = hệ số % rủi ro theo đèn."""
    return _portfolio_risk()


@app.post("/api/positions")
def pos_add(item: PositionIn):
    code = item.sym.strip().upper()
    R, a = _analysis(code, item.entry_d and item.entry_d.isoformat())
    plan = (a or {}).get("plan") or {}
    entry_px = item.entry_px or R[-1]["c"]
    stop = item.stop or plan.get("stop")
    targets = item.targets if item.targets is not None else [t["price"] for t in plan.get("targets", [])]
    if not stop or stop >= entry_px:
        raise HTTPException(400, f"Cắt lỗ {stop or '–'} không thấp hơn giá vào {entry_px}: lệnh mua ngoài kế hoạch "
                                 "(kế hoạch mua ở vùng khác) - hãy nhập mốc cắt lỗ của bạn.")
    conn.execute("INSERT INTO positions(sym,kind,entry_d,entry_px,qty,stop,stop0,targets,note) VALUES (?,?,?,?,?,?,?,?,?)",
                 (code, plan.get("kind"), R[-1]["d"], entry_px, item.qty, stop, stop, json.dumps(targets), item.note))
    conn.execute("INSERT OR IGNORE INTO watchlist(sym) VALUES (?)", (code,))   # để luôn được quét; "đang giữ" tính từ Danh mục
    conn.commit()
    return pos_list()


@app.post("/api/positions/{pid}/sell")
def pos_sell(pid: int, item: SellIn):
    """Ghi một lần bán. Bán hết phần còn giữ (hoặc lệnh không ghi KL) thì đóng lệnh, giá thoát = giá bán bình quân."""
    row = conn.execute("SELECT sym, qty, entry_d FROM positions WHERE id=? AND status='open'", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "Không có lệnh đang giữ này")
    sold = conn.execute("SELECT COALESCE(sum(qty),0) FROM sales WHERE pos_id=?", (pid,)).fetchone()[0]
    left = row["qty"] - sold if row["qty"] else None
    qty = item.qty or left
    if left is not None and qty > left:
        raise HTTPException(400, f"Chỉ còn giữ {left} cp")
    last = conn.execute("SELECT d, c FROM ohlcv WHERE sym=? ORDER BY d DESC LIMIT 1", (row["sym"],)).fetchone()
    d = item.d.isoformat() if item.d else last["d"]
    if d < row["entry_d"]:
        raise HTTPException(400, "Ngày bán trước ngày mua")
    conn.execute("INSERT INTO sales(pos_id, d, px, qty) VALUES (?,?,?,?)", (pid, d, item.px or last["c"], qty))
    if left is None or qty == left:
        avg = conn.execute("SELECT sum(px*COALESCE(qty,1))/sum(COALESCE(qty,1)), max(d) FROM sales WHERE pos_id=?",
                           (pid,)).fetchone()
        conn.execute("UPDATE positions SET status='closed', exit_d=?, exit_px=? WHERE id=?", (avg[1], avg[0], pid))
    conn.commit()
    return pos_list()


@app.get("/api/sales")
def sales_list():
    """Lịch sử bán, mới nhất trước; lãi/lỗ sau phí (mua 0,15%, bán 0,15% + thuế 0,1%)."""
    rows = conn.execute(
        "SELECT s.id, s.d, s.px, s.qty, p.id AS pos_id, p.sym, p.entry_d, p.entry_px FROM sales s "
        "JOIN positions p ON p.id = s.pos_id "
        "UNION ALL "   # lệnh đóng trước khi có bảng sales: coi như một lần bán hết
        "SELECT NULL, exit_d, exit_px, qty, id, sym, entry_d, entry_px FROM positions p "
        "WHERE status='closed' AND NOT EXISTS (SELECT 1 FROM sales WHERE pos_id=p.id) "
        "ORDER BY 2 DESC, 1 DESC").fetchall()
    out = []
    for r in rows:
        net = r["px"] * (1 - SELL_FEE) - r["entry_px"] * (1 + BUY_FEE)   # nghìn đồng / cp
        out.append(dict(r, pnl=round(net / (r["entry_px"] * (1 + BUY_FEE)) * 100, 1),
                        pnl_vnd=round(net * 1000 * r["qty"]) if r["qty"] else None))
    return out


class StopIn(BaseModel):
    stop: float = Field(gt=0)            # nghìn đồng


@app.patch("/api/positions/{pid}")
def pos_stop(pid: int, item: StopIn):
    # shortcut: thay mốc gốc rồi simulate chạy lại từ ngày mua, nên mốc cao hơn các giá đóng cửa cũ sẽ
    # cho "Cắt lỗ" ở quá khứ; cần lịch sử dời cắt lỗ theo ngày nếu hay sửa mốc lên cao.
    if not conn.execute("UPDATE positions SET stop=? WHERE id=? AND status='open'", (item.stop, pid)).rowcount:
        raise HTTPException(404, "Không có lệnh đang giữ này")
    conn.commit()
    return pos_list()


@app.delete("/api/sales/{sid}")
def sale_del(sid: int):
    """Xóa một lần bán (ghi nhầm); lệnh đã đóng thì mở lại với phần cp tương ứng."""
    row = conn.execute("SELECT pos_id FROM sales WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(404, "Không có lần bán này")
    conn.execute("DELETE FROM sales WHERE id=?", (sid,))
    conn.execute("UPDATE positions SET status='open', exit_d=NULL, exit_px=NULL WHERE id=?", (row["pos_id"],))
    conn.commit()
    return sales_list()


@app.delete("/api/positions/{pid}")
def pos_del(pid: int):
    conn.execute("DELETE FROM sales WHERE pos_id=?", (pid,))
    conn.execute("DELETE FROM positions WHERE id=?", (pid,)); conn.commit()
    return pos_list()


def _run_scan(dry_run: bool):
    started = health_mod.now_vn().isoformat(timespec="seconds")
    try:
        _scan_state["last"] = r = scan_mod.run(dry_run=dry_run)
        if not dry_run:                          # nút Quét lại trên web: ghi như lần quét tự động
            health_mod.record(conn, "scan", started, "skipped" if r.get("skipped") else "ok", scan_mod.job_detail(r))
    except Exception as e:
        if not dry_run:
            health_mod.record(conn, "scan", started, "error", dict(error=str(e)[:500]))
        raise
    finally:
        _scan_state["running"] = False


VN_TZ = dt.timezone(dt.timedelta(hours=7))


def scan_allowed(now: dt.datetime | None = None) -> bool:
    """Chỉ quét từ 15:00 thứ 2–6 (giờ VN): trước đó nến hôm nay chưa chốt, giá đóng cửa và KL sai."""
    now = now or dt.datetime.now(VN_TZ)
    return now.weekday() < 5 and now.hour >= 15


@app.post("/api/scan/run")
def scan_run(bg: BackgroundTasks, dry_run: bool = True):
    if not scan_allowed():
        raise HTTPException(403, "Chỉ quét được từ 15:00 thứ 2–6 (sau khi phiên kết thúc).")
    with _lock:
        if _scan_state["running"]:
            return dict(status="running")
        _scan_state["running"] = True
    bg.add_task(_run_scan, dry_run)
    return dict(status="started")


@app.get("/api/scan/status")
def scan_status():
    last = _scan_state["last"]
    return dict(running=_scan_state["running"],
                last=last and dict(date=last["date"], n=last["n"], errors=last["errors"], signals=len(last["signals"])))
