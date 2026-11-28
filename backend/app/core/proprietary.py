"""Tự doanh công ty chứng khoán mua/bán theo mã (nguồn CafeF, API không chính thức), lưu bảng prop_trade.

CafeF chỉ trả ~1 năm gần nhất và chỉ có dòng cho phiên tự doanh có giao dịch: phiên giao dịch (theo nến giá) không có
dòng nghĩa là tự doanh không mua bán mã đó (0). Bảng prop_meta ghi tới phiên nào đã kiểm tra (upto) và dữ liệu có từ
ngày nào (since), để không tải lại khi không có gì mới.
"""
import datetime as dt
import json
import urllib.request

URL = ("https://cafef.vn/du-lieu/Ajax/PageNew/DataHistory/GDTuDoanh.ashx?Symbol={s}&StartDate=&EndDate="
       "&PageIndex=1&PageSize={n}")
HEADERS = {"User-Agent": "Mozilla/5.0"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS prop_trade (sym TEXT NOT NULL, d TEXT NOT NULL, buy REAL, sell REAL, PRIMARY KEY (sym, d));
CREATE TABLE IF NOT EXISTS prop_meta (sym TEXT PRIMARY KEY, upto TEXT, since TEXT);
"""


def _iso(s: str) -> str:
    return dt.datetime.strptime(s, "%d/%m/%Y").date().isoformat()


def fetch(sym: str, size: int = 400) -> tuple[list[dict], str | None]:
    """(các phiên có giao dịch tự doanh, giảm dần: d, buy, sell tỷ đồng; phiên dữ liệu mới nhất của nguồn)."""
    j = json.load(urllib.request.urlopen(urllib.request.Request(URL.format(s=sym, n=size), headers=HEADERS), timeout=30))
    data = (j or {}).get("Data") or {}
    rows = ((data.get("Data") or {}).get("ListDataTudoanh")) or []
    return ([dict(d=_iso(r["Date"]), buy=round((r.get("GtMua") or 0) / 1e9, 4), sell=round((r.get("GtBan") or 0) / 1e9, 4))
             for r in rows], _iso(data["DateIndex"]) if data.get("DateIndex") else None)


def _store(conn, sym: str, got: list[dict], upto: str | None) -> tuple:
    """Ghi kết quả tải của một mã (thay toàn bộ dòng cũ) + prop_meta; trả (upto, since). Chưa commit."""
    conn.execute("DELETE FROM prop_trade WHERE sym=?", (sym,))
    conn.executemany("INSERT OR REPLACE INTO prop_trade(sym,d,buy,sell) VALUES (?,?,?,?)",
                     [(sym, r["d"], r["buy"], r["sell"]) for r in got])
    # nguồn có thể chưa có phiên hôm nay: chỉ coi là "đã kiểm tra" tới phiên nguồn có
    since = min((r["d"] for r in got), default=None)
    conn.execute("INSERT OR REPLACE INTO prop_meta(sym, upto, since) VALUES (?,?,?)",
                 (sym, upto or (got[0]["d"] if got else None), since))
    return upto, since


def sync_prop(conn, syms: list[str], upto: str, workers: int = 6, fetcher=None) -> list[str]:
    """Tải tự doanh cho các mã chưa có prop_meta hoặc prop_meta.upto < upto. Luồng phụ chỉ gọi mạng, ghi DB tuần tự
    ở luồng gọi hàm (giống foreign.sync_foreign). fetcher=None: hàm fetch của module (test thay được). Trả mã lỗi."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time
    fetcher = fetcher or fetch
    conn.executescript(SCHEMA)
    meta = {r[0]: r[1] for r in conn.execute("SELECT sym, upto FROM prop_meta")}
    need = [s.upper() for s in syms if not meta.get(s.upper()) or meta[s.upper()] < upto]
    errors = []

    def job(s):
        time.sleep(0.05)
        try:
            return s, fetcher(s)
        except Exception:
            return s, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(job, s) for s in need]):
            s, got = f.result()
            if got is None:
                errors.append(s); continue
            _store(conn, s, got[0], got[1])
    conn.commit()
    return errors


def prop_net(conn, sym: str, upto: str, n: int = 20, max_lag: int = 2) -> dict | None:
    """Tự doanh mua ròng (tỷ đồng) n phiên và 5 phiên tới `upto`, chỉ đọc DB. Phiên giao dịch không có dòng = 0.
    None khi: chưa tải; nguồn trễ hơn max_lag phiên giao dịch so với `upto` (CafeF hay trễ, lúc quét 15:30 có thể
    chưa có phiên hôm nay); hoặc phiên đầu của n phiên trước ngày nguồn bắt đầu có dữ liệu."""
    import sqlite3
    try:
        meta = conn.execute("SELECT upto, since FROM prop_meta WHERE sym=?", (sym,)).fetchone()
    except sqlite3.OperationalError:            # chưa có bảng (chưa tải lần nào)
        return None
    if not meta or not meta[0] or not meta[1]:
        return None
    src_upto, since = meta[0], meta[1]
    lag = conn.execute("SELECT count(*) FROM ohlcv WHERE sym=? AND d>? AND d<=?", (sym, src_upto, upto)).fetchone()[0]
    if lag > max_lag:
        return None
    end = min(src_upto, upto)
    days = [r[0] for r in conn.execute("SELECT d FROM ohlcv WHERE sym=? AND d<=? ORDER BY d DESC LIMIT ?", (sym, end, n))][::-1]
    if len(days) < n or days[0] < since:
        return None
    have = {r[0]: r[1] for r in conn.execute("SELECT d, buy - sell FROM prop_trade WHERE sym=? AND d>=? AND d<=?",
                                            (sym, days[0], end))}
    nets = [have.get(d) or 0.0 for d in days]
    return dict(net=round(sum(nets), 2), net5=round(sum(nets[-5:]), 2), upto=src_upto, lag=lag)


def get_prop(conn, sym: str, end: str | None = None, n: int = 250, fetcher=fetch):
    """(rows tăng dần theo phiên giao dịch: d, buy, sell, net; lỗi hoặc None): `n` phiên tới `end`, phiên không có
    giao dịch tự doanh = 0, bỏ các phiên trước khi nguồn có dữ liệu. Tải lại khi nguồn có thể có phiên mới hơn."""
    sym = sym.upper()
    conn.executescript(SCHEMA)
    q = "SELECT d FROM ohlcv WHERE sym=?" + (" AND d<=?" if end else "") + " ORDER BY d DESC LIMIT ?"
    days = [r[0] for r in conn.execute(q, (sym, end, n) if end else (sym, n))][::-1]
    if not days:
        return [], None
    meta = conn.execute("SELECT upto, since FROM prop_meta WHERE sym=?", (sym,)).fetchone()
    err = None
    if not meta or (meta[0] or "") < days[-1]:
        try:
            got, upto = fetcher(sym)
            meta = _store(conn, sym, got, upto)
            conn.commit()
        except Exception as e:                 # mất mạng / CafeF đổi API: dùng phần đã lưu
            err = str(e)
    since, upto = (meta[1], meta[0]) if meta else (None, None)
    if not since:
        return [], err
    have = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT d, buy, sell FROM prop_trade WHERE sym=? AND d>=?", (sym, days[0]))}
    out = []
    for d in days:
        if d < since or (upto and d > upto):     # ngoài khoảng nguồn có dữ liệu: không coi là 0
            continue
        b, s = have.get(d, (0.0, 0.0))
        out.append(dict(d=d, buy=b, sell=s, net=round(b - s, 4)))
    return out, err
