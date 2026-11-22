"""REST API cho web Next.js.  Chạy: .venv\\Scripts\\uvicorn app.api:app --port 8000"""
import json, threading, datetime as dt
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .db import connect
from .core.data import get_ohlcv
from .core.wyckoff import analyse, trim, ANALYSIS_DAYS
from .core.market import traffic_light
from .core.positions import simulate
from .core.foreign import get_foreign
from .universe import GROUP_NAMES, INDEX, group_of, watchlist, listing, sectors
from . import scan as scan_mod
from .core.signals import PRIORITY
from .backtest import BUY_FEE, SELL_FEE

app = FastAPI(title="Wyckoff Scanner")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])
conn = connect()
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


@app.get("/api/market")
def market(date: str | None = None):
    d = _session(date)
    row = conn.execute("SELECT data FROM scan_results WHERE sym=? AND date=?", (INDEX, d)).fetchone() if d else None
    res = json.loads(row[0]) if row else None
    return dict(date=d, **traffic_light(res, res and res.get("breadth")), tag=res and res.get("tag"))


@app.get("/api/scan/latest")
def scan_latest(group: str | None = None, date: str | None = None):
    d = _session(date)
    if not d:
        return dict(date=None, rows=[])
    wl = set(watchlist(conn))
    lst = listing(conn)
    rows = []
    for sym, data in conn.execute("SELECT sym, data FROM scan_results WHERE date=? AND sym<>?", (d, INDEX)):
        r = json.loads(data)
        gs = group_of(sym, lst) + (["wl"] if sym in wl else [])
        if group and group not in gs:
            continue
        info = lst.get(sym, {})
        p = r.get("plan") or {}
        rows.append(dict(sym=sym, groups=gs, floor=info.get("floor"), name=info.get("name"),
                         ready=(p.get("ready") or {}).get("score"), rr=p.get("rr"), plan_kind=p.get("kind"),
                         entry_lo=p.get("entry_lo"), entry_hi=p.get("entry_hi"), stop=p.get("stop"),
                         in_zone=p.get("in_zone"),
                         tag=r["tag"], stage=r["stage"], c=r["c"], chg=r["chg"],
                         liq=r["liq"], rs5=r.get("rs5"), rs20=r.get("rs20"), rs60=r.get("rs60"),
                         dist=r.get("dist"), extra=r.get("extra"), weak_drop=r.get("weak_drop"),
                         levels=r.get("levels"), pos52=r.get("pos52"), fx10=r.get("fx10")))
    return dict(date=d, rows=rows, groups=GROUP_NAMES, sectors=sectors(conn))


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
    fx, fx_err = get_foreign(conn, code, at) if len(code) == 3 else ([], None)   # khối ngoại: chỉ cổ phiếu
    kind = ((res or {}).get("plan") or {}).get("kind")
    st = kind and conn.execute("SELECT * FROM backtest_stats WHERE plan=?", (kind.split(" (")[0],)).fetchone()
    lst = listing(conn)
    info = lst.get(code, {})
    return dict(sym=code, groups=group_of(code, lst), name=info.get("name"), floor=info.get("floor"),
                sector=info.get("icb_name"), unit="pt" if len(code) > 3 else "k",    # VNM, VND... là cổ phiếu
                ohlcv=full,
                analysis=res, signals=signals(120, code, at), at=at, start=start, foreign=fx, foreign_error=fx_err, plan_stats=dict(st) if st else None, in_watchlist=code in watchlist(conn))


class WatchItem(BaseModel):
    sym: str
    note: str | None = None


@app.get("/api/watchlist")
def wl_get():
    return [dict(r) for r in conn.execute("SELECT sym, note, added FROM watchlist ORDER BY sym")]


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
    out = []
    for row in conn.execute("SELECT * FROM positions WHERE status='open' ORDER BY entry_d DESC, id DESC").fetchall():
        p = dict(row, targets=json.loads(row["targets"] or "[]"))
        p["sold"] = conn.execute("SELECT COALESCE(sum(qty),0) FROM sales WHERE pos_id=?", (p["id"],)).fetchone()[0]
        bars = [r for r in get_ohlcv(conn, p["sym"], 4000, refresh=False) if r["d"] >= p["entry_d"]]
        if bars:
            s = simulate(p["entry_px"], p["stop"], p["targets"], bars)
            p.update(c=bars[-1]["c"], d=bars[-1]["d"], days=len(bars) - 1,
                     pnl=round((bars[-1]["c"] / p["entry_px"] - 1) * 100, 1),
                     cur_stop=s["stop"], left=s["left"], hit=s["hit"], next=s["next"], pending=s["pending"],
                     sold_out=None if s["open"] else s["exits"][-1]["d"], events=s["events"][-3:])
        out.append(p)
    return out


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
    conn.execute("INSERT INTO positions(sym,kind,entry_d,entry_px,qty,stop,targets,note) VALUES (?,?,?,?,?,?,?,?)",
                 (code, plan.get("kind"), R[-1]["d"], entry_px, item.qty, stop, json.dumps(targets), item.note))
    conn.execute("INSERT OR IGNORE INTO watchlist(sym, note) VALUES (?, ?)", (code, "đang giữ"))   # để luôn được quét
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
    try:
        _scan_state["last"] = scan_mod.run(dry_run=dry_run)
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
