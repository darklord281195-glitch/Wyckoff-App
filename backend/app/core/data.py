"""Lấy giá ngày (VNDirect dchart, giá đã điều chỉnh) + cache vào SQLite.

API không chính thức: muốn đổi nguồn chỉ cần thay fetch_remote().
"""
import json, time, datetime as dt, urllib.request

API = "https://dchart-api.vndirect.com.vn/dchart/history?resolution={r}&symbol={s}&from={f}&to={t}"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_remote(sym: str, days: int, retries: int = 3, res: str = "D") -> list[dict]:
    """res="D": nến ngày, d = 'YYYY-MM-DD'; res="60": nến 1 giờ, d = 'YYYY-MM-DDTHH:MM' giờ VN."""
    to = int(time.time()); fr = to - days * 86400
    url = API.format(s=sym, f=fr, t=to, r=res)
    last_err = None
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            j = json.load(urllib.request.urlopen(req, timeout=30))
            if j.get("s") != "ok" or not j.get("t"):
                return []
            day = (lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")) if res == "D" else                   (lambda t: dt.datetime.fromtimestamp(t, dt.timezone(dt.timedelta(hours=7))).strftime("%Y-%m-%dT%H:%M"))
            return [dict(d=day(t), o=o, h=h, l=l, c=c, v=v / 1e6)
                    for t, o, h, l, c, v in zip(j["t"], j["o"], j["h"], j["l"], j["c"], j["v"])]
        except Exception as e:                                   # mạng chập chờn: thử lại
            last_err = e; time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{sym}: lỗi tải dữ liệu ({last_err})")


def sync_many(conn, syms: list[str], days: int = 500, workers: int = 6, on_error=None, full: bool = False) -> list[str]:
    """Cập nhật dữ liệu nhiều mã song song: tải mạng trong thread pool, ghi DB ở thread chính.
    full=True: tải lại toàn bộ `days` ngày (vd lấy lịch sử dài cho backtest). Trả về danh sách mã bị lỗi."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    today = dt.date.today()
    plan = {}
    for s in syms:
        last = None if full else conn.execute("SELECT max(d) FROM ohlcv WHERE sym=?", (s,)).fetchone()[0]
        plan[s] = (last, days if last is None else (today - dt.date.fromisoformat(last)).days + 7)
    errors = []

    def job(s):
        time.sleep(0.05)
        return s, fetch_remote(s, max(plan[s][1], 7))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(job, s) for s in syms]
        for f in as_completed(futs):
            try:
                s, rows = f.result()
            except Exception as e:
                errors.append(str(e).split(":")[0]); on_error and on_error(e); continue
            last = plan[s][0]
            if rows and last is not None:
                old = conn.execute("SELECT c FROM ohlcv WHERE sym=? AND d=?", (s, rows[0]["d"])).fetchone()
                if old and abs(old[0] - rows[0]["c"]) / max(old[0], 1e-9) > 0.005:   # giá điều chỉnh đổi
                    conn.execute("DELETE FROM ohlcv WHERE sym=?", (s,))
                    rows = fetch_remote(s, days)
            conn.executemany("INSERT OR REPLACE INTO ohlcv(sym,d,o,h,l,c,v) VALUES (?,?,?,?,?,?,?)",
                             [(s, r["d"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in rows])
    conn.commit()
    return errors


def get_ohlcv(conn, sym: str, days: int = 500, refresh: bool = True) -> list[dict]:
    """Trả list OHLCV tăng dần theo ngày. Chỉ tải phần còn thiếu, luôn tải lại 5 ngày cuối
    (phiên hôm nay có thể chưa chốt, giá điều chỉnh có thể đổi khi chia cổ tức)."""
    sym = sym.upper()
    if refresh:
        last = conn.execute("SELECT max(d) FROM ohlcv WHERE sym=?", (sym,)).fetchone()[0]
        need = days if last is None else (dt.date.today() - dt.date.fromisoformat(last)).days + 7
        rows = fetch_remote(sym, max(need, 7))
        if rows and last is not None:
            # giá điều chỉnh đổi (chia tách/cổ tức) -> tải lại toàn bộ
            old = conn.execute("SELECT c FROM ohlcv WHERE sym=? AND d=?", (sym, rows[0]["d"])).fetchone()
            if old and abs(old[0] - rows[0]["c"]) / max(old[0], 1e-9) > 0.005:
                conn.execute("DELETE FROM ohlcv WHERE sym=?", (sym,))
                rows = fetch_remote(sym, days)
        conn.executemany("INSERT OR REPLACE INTO ohlcv(sym,d,o,h,l,c,v) VALUES (?,?,?,?,?,?,?)",
                         [(sym, r["d"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in rows])
        conn.commit()
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    cur = conn.execute("SELECT d,o,h,l,c,v FROM ohlcv WHERE sym=? AND d>=? ORDER BY d", (sym, since))
    return [dict(r) for r in cur.fetchall()]
