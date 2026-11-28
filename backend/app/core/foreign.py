"""Giao dịch khối ngoại theo phiên (VNDirect finfo /foreigns, API không chính thức).

Tải khi mở trang mã rồi lưu bảng foreign_trade; giá trị lưu theo tỷ đồng.
Chỉ có cho cổ phiếu (chỉ số VNINDEX trên API này đã ngừng cập nhật)."""
import json, time, urllib.request

FINFO = "https://api-finfo.vndirect.com.vn/v4/foreigns"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MAX_SESSIONS = 250                     # khoảng dài nhất trên web (~1 năm); "Theo vùng" có thể cần dài hơn


def fetch(sym: str, end: str | None = None, size: int = MAX_SESSIONS + 20) -> list[dict]:
    """Các phiên gần nhất tới `end` (mặc định mới nhất), giảm dần theo ngày."""
    q = f"code:{sym}" + (f"~tradingDate:lte:{end}" if end else "")
    url = f"{FINFO}?q={q}&sort=tradingDate&size={size}"
    data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30))["data"]
    return [dict(d=r["tradingDate"], buy=(r.get("buyVal") or 0) / 1e9, sell=(r.get("sellVal") or 0) / 1e9,
                 net=(r.get("netVal") or 0) / 1e9, net_vol=r.get("netVol"),
                 room=r.get("currentRoom"), total_room=r.get("totalRoom")) for r in data]


def sync_foreign(conn, syms: list[str], upto: str, workers: int = 6, fetcher=None) -> list[str]:
    """Tải khối ngoại cho các mã chưa có phiên `upto` (tải mạng trong thread pool, ghi DB ở thread chính,
    giống core.data.sync_many). Chưa có gì thì tải 110 phiên, có rồi thì 15. Trả danh sách mã lỗi."""
    need = {}
    for s in syms:
        last = conn.execute("SELECT max(d) FROM foreign_trade WHERE sym=?", (s,)).fetchone()[0]
        if not last or last < upto:
            need[s] = 15 if last else MAX_SESSIONS + 20
    return _download(conn, need, workers, fetcher or fetch)


HISTORY_SESSIONS = 2100                # ~8 năm, cho backtest --compare


def backfill_foreign(conn, syms: list[str], workers: int = 6, fetcher=None) -> list[str]:
    """Tải ~8 năm khối ngoại cho các mã (backtest kiểm chứng bộ lọc khối ngoại). Trả danh sách mã lỗi."""
    return _download(conn, {s: HISTORY_SESSIONS for s in syms}, workers, fetcher or fetch)


def _download(conn, need: dict[str, int], workers, fetcher) -> list[str]:
    """Tải {mã: số phiên} trong thread pool, ghi DB ở thread chính (giống core.data.sync_many)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    errors = []

    def job(s):
        time.sleep(0.05)
        try:
            return s, fetcher(s, None, need[s])
        except Exception:
            return s, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(job, s) for s in need]):
            s, got = f.result()
            if got is None:
                errors.append(s); continue
            conn.executemany("INSERT OR REPLACE INTO foreign_trade(sym,d,buy,sell,net,net_vol,room,total_room) "
                             "VALUES (?,?,?,?,?,?,?,?)",
                             [(s, r["d"], r["buy"], r["sell"], r["net"], r["net_vol"], r["room"], r["total_room"]) for r in got])
    conn.commit()
    return errors


def net_sum(conn, sym: str, upto: str, n: int = 10):
    """Tổng giá trị mua ròng (tỷ đồng) `n` phiên khối ngoại gần nhất tới `upto`; None nếu chưa đủ `n` phiên
    hoặc phiên cuối không phải `upto` (dữ liệu cũ, dễ hiểu nhầm)."""
    rows = conn.execute("SELECT d, net FROM foreign_trade WHERE sym=? AND d<=? ORDER BY d DESC LIMIT ?",
                        (sym, upto, n)).fetchall()
    if len(rows) < n or rows[0][0] != upto:
        return None
    return round(sum(r[1] for r in rows), 2)


def _stored(conn, sym, end, n):
    q = "SELECT d, buy, sell, net, net_vol, room, total_room FROM foreign_trade WHERE sym=?"
    args = [sym]
    if end:
        q += " AND d<=?"; args.append(end)
    rows = [dict(r) for r in conn.execute(q + " ORDER BY d DESC LIMIT ?", (*args, n))]
    return rows[::-1]


def get_foreign(conn, sym: str, end: str | None = None, n: int = MAX_SESSIONS, fetcher=fetch):
    """(rows tăng dần, lỗi hoặc None): `n` phiên khối ngoại gần nhất tới `end`.
    Tải lại khi DB thiếu phiên: chưa đủ `n` phiên, hoặc phiên cuối cũ hơn nến giá cuối (tới `end`)."""
    sym = sym.upper()
    rows = _stored(conn, sym, end, n)
    q = "SELECT max(d), count(*) FROM ohlcv WHERE sym=?" + (" AND d<=?" if end else "")
    last_px, n_px = conn.execute(q, (sym, end) if end else (sym,)).fetchone()
    # mã mới niêm yết có ít phiên hơn n: đủ khi đã có gần hết số phiên giá (không tải lại mỗi lần mở trang)
    enough = len(rows) >= min(n, max(n_px - 5, 1)) if n_px else len(rows) >= n
    if rows and enough and (not last_px or rows[-1]["d"] >= last_px):
        return rows, None
    try:
        got = fetcher(sym, end, size=n + 20)
    except Exception as e:                     # mất mạng / API đổi: vẫn trả phần đã lưu
        return rows, str(e)
    conn.executemany("INSERT OR REPLACE INTO foreign_trade(sym,d,buy,sell,net,net_vol,room,total_room) VALUES (?,?,?,?,?,?,?,?)",
                     [(sym, r["d"], r["buy"], r["sell"], r["net"], r["net_vol"], r["room"], r["total_room"]) for r in got])
    conn.commit()
    return _stored(conn, sym, end, n), None
