"""Lấy giá ngày (VNDirect dchart, giá đã điều chỉnh) + cache vào SQLite.

API không chính thức: muốn đổi nguồn chỉ cần thay fetch_remote().
Nguồn dự phòng (nến ngày): DNSE/Entrade chart API, cùng đơn vị giá (nghìn đồng), KL theo cổ phiếu. Chỉ dùng khi VNDirect
lỗi, và chỉ để NỐI THÊM phiên mới: các phiên trùng phải khớp giá đóng cửa trong DB (≤ 0,5%), KL quy đổi theo tỷ lệ các
phiên trùng (VNINDEX của DNSE tính KL khác ~30%). Không bao giờ tải lại toàn bộ lịch sử từ nguồn dự phòng.
"""
import json, time, datetime as dt, urllib.request

API = "https://dchart-api.vndirect.com.vn/dchart/history?resolution={r}&symbol={s}&from={f}&to={t}"
FALLBACK_API = "https://services.entrade.com.vn/chart-api/v2/ohlcs/{kind}?from={f}&to={t}&symbol={s}&resolution=1D"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MATCH_TOL = 0.005                     # giá đóng cửa các phiên trùng: lệch tối đa 0,5% mới coi là cùng thang giá
FALLBACK_USED: set[str] = set()       # mã đã phải lấy từ nguồn dự phòng (đọc sau mỗi lần đồng bộ, vd lần quét)


class Rows(list):
    """Danh sách nến kèm nguồn (src) để nơi ghi DB biết dữ liệu dự phòng thì chỉ được nối thêm."""
    src = "vndirect"


def fetch_fallback(sym: str, days: int) -> Rows:
    """Nến ngày từ DNSE (dự phòng). Mã dài hơn 3 ký tự coi là chỉ số. KL đổi sang triệu cp như VNDirect."""
    to = int(time.time()); fr = to - days * 86400
    url = FALLBACK_API.format(kind="index" if len(sym) > 3 else "stock", s=sym, f=fr, t=to)
    j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30))
    if not j.get("t"):
        return Rows()
    day = lambda t: dt.datetime.fromtimestamp(t, dt.timezone(dt.timedelta(hours=7))).strftime("%Y-%m-%d")
    out = Rows(dict(d=day(t), o=o, h=h, l=l, c=c, v=v / 1e6) for t, o, h, l, c, v in zip(j["t"], j["o"], j["h"], j["l"], j["c"], j["v"]))
    out.src = "dnse"
    return out


def merge_fallback(conn, sym: str, rows: list[dict], last: str | None) -> list[dict] | None:
    """Các phiên mới (sau `last`) của dữ liệu dự phòng, KL đã quy đổi theo tỷ lệ các phiên trùng với DB.
    None nếu không dùng được: chưa có lịch sử để đối chiếu, không có phiên trùng, hoặc giá lệch thang (điều chỉnh khác)."""
    if not rows or last is None:
        return None
    old = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT d, c, v FROM ohlcv WHERE sym=? AND d>=?", (sym, rows[0]["d"]))}
    both = [(r, old[r["d"]]) for r in rows if r["d"] in old]
    if not both or any(abs(r["c"] / max(c, 1e-9) - 1) > MATCH_TOL for r, (c, _) in both):
        return None
    ratio = sorted(v / r["v"] for r, (_, v) in both if r["v"] > 0 and v)
    k = ratio[len(ratio) // 2] if ratio else 1.0
    return [dict(r, v=round(r["v"] * k, 6)) for r in rows if r["d"] > last]


def fetch_remote(sym: str, days: int, retries: int = 3, res: str = "D") -> list[dict]:
    """res="D": nến ngày, d = 'YYYY-MM-DD'; res="60": nến 1 giờ, d = 'YYYY-MM-DDTHH:MM' giờ VN.
    Nến ngày: VNDirect lỗi hết lượt thử thì lấy từ nguồn dự phòng (kết quả là Rows có src="dnse", ghi vào FALLBACK_USED)."""
    to = int(time.time()); fr = to - days * 86400
    url = API.format(s=sym, f=fr, t=to, r=res)
    last_err = None
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            j = json.load(urllib.request.urlopen(req, timeout=30))
            if j.get("s") != "ok" or not j.get("t"):
                return Rows()
            day = (lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")) if res == "D" else                   (lambda t: dt.datetime.fromtimestamp(t, dt.timezone(dt.timedelta(hours=7))).strftime("%Y-%m-%dT%H:%M"))
            return Rows(dict(d=day(t), o=o, h=h, l=l, c=c, v=v / 1e6)
                        for t, o, h, l, c, v in zip(j["t"], j["o"], j["h"], j["l"], j["c"], j["v"]))
        except Exception as e:                                   # mạng chập chờn: thử lại
            last_err = e; time.sleep(1.5 * (k + 1))
    if res == "D":
        try:
            rows = fetch_fallback(sym, days)
            if rows:
                FALLBACK_USED.add(sym)
                return rows
        except Exception as e:
            last_err = f"{last_err}; dự phòng: {e}"
    raise RuntimeError(f"{sym}: lỗi tải dữ liệu ({last_err})")


def add_atc(hourly: list[dict], daily: list[dict]) -> list[dict]:
    """Nến 1 giờ của VNDirect không gồm phiên ATC (14:30–14:45): gộp phần còn thiếu vào nến cuối mỗi ngày
    từ nến ngày (giá đóng cửa, cao/thấp, khối lượng). Bỏ qua ngày lệch giá mở cửa > 0,5% (giá ngày đã điều chỉnh
    cổ tức/chia tách còn giá giờ thì không) để không trộn hai thang giá."""
    by_day = {r["d"]: r for r in daily}
    last, first, vol = {}, {}, {}
    for i, r in enumerate(hourly):
        day = r["d"][:10]
        first.setdefault(day, r); last[day] = i; vol[day] = vol.get(day, 0) + r["v"]
    out = [dict(r) for r in hourly]
    for day, i in last.items():
        D = by_day.get(day)
        if not D or abs(D["o"] - first[day]["o"]) > 0.005 * max(D["o"], 1e-9):
            continue
        b = out[i]
        b["c"] = D["c"]; b["h"] = max(b["h"], D["c"]); b["l"] = min(b["l"], D["c"])
        b["v"] = round(b["v"] + max(D["v"] - vol[day], 0), 6)
    return out


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
            if getattr(rows, "src", "vndirect") != "vndirect":      # nguồn dự phòng: chỉ nối thêm phiên mới
                rows = merge_fallback(conn, s, rows, last)
                if rows is None:
                    errors.append(s); continue
            elif rows and last is not None:
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
        if getattr(rows, "src", "vndirect") != "vndirect":          # nguồn dự phòng: chỉ nối thêm phiên mới
            rows = merge_fallback(conn, sym, rows, last) or []
        elif rows and last is not None:
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
