"""Chỉ số cơ bản từ BCTC quý (VNDirect finfo /financial_statements, API không chính thức).

Chỉ dùng báo cáo đã CÔNG BỐ trước ngày xét (createdDate ≤ d) để backtest không "nhìn trước tương lai".
Mã chỉ tiêu dùng chung mọi loại doanh nghiệp: 23000 LNST của cổ đông công ty mẹ, 14000 vốn chủ sở hữu;
doanh nghiệp thường thêm 21001 doanh thu thuần, 13110 + 13340 vay và nợ ngắn/dài hạn. Giá trị lưu theo tỷ đồng."""
import json
import time
import datetime as dt
import urllib.request

FINFO = "https://api-finfo.vndirect.com.vn/v4"
HEADERS = {"User-Agent": "Mozilla/5.0"}
ITEMS = {23000: "np", 14000: "equity", 21001: "revenue", 13110: "debt_st", 13340: "debt_lt"}
MAIN_MODELS = {1, 2, 89, 90, 101, 102, 411, 412}      # mẫu BCĐKT/KQKD chính theo loại doanh nghiệp
REFRESH_DAYS = 7


def fetch(sym: str) -> list[tuple]:
    """[(quý, ngày công bố, chỉ tiêu, giá trị tỷ đồng)] mọi quý có dữ liệu; một chỉ tiêu/quý chỉ giữ mẫu chính."""
    q = f"code:{sym}~reportType:QUARTER~itemCode:{','.join(str(k) for k in ITEMS)}"
    url = f"{FINFO}/financial_statements?q={q}&sort=fiscalDate:desc&size=2000"
    data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60))["data"]
    best = {}
    for r in data:
        k = (r["fiscalDate"], int(r["itemCode"]))
        main = int(r.get("modelType") or 0) in MAIN_MODELS
        if k not in best or (main and not best[k][0]):
            best[k] = (main, (r.get("createdDate") or r["fiscalDate"])[:10], r["numericValue"])
    return [(f, c, ITEMS[item], v / 1e9) for (f, item), (_, c, v) in best.items() if item in ITEMS and v is not None]


def fetch_pe(sym: str):
    """P/E và vốn hóa (tỷ đồng) mới nhất từ /ratios/latest; None nếu không có."""
    url = (f"{FINFO}/ratios/latest?filter=itemCode:51003,51006&where=code:{sym}"
           f"&order=reportDate&fields=itemCode,value,reportDate")
    data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30))["data"]
    v = {str(r["itemCode"]): r["value"] for r in data}
    return dict(pe=v.get("51006"), mcap=v["51003"] / 1e9 if v.get("51003") else None)


def save(conn, sym, rows):
    conn.execute("DELETE FROM fin_quarter WHERE sym=?", (sym,))
    conn.executemany("INSERT OR REPLACE INTO fin_quarter(sym,fiscal,created,item,value) VALUES (?,?,?,?,?)",
                     [(sym, *r) for r in rows])
    conn.execute("INSERT OR REPLACE INTO fin_meta(sym,fetched) VALUES (?,?)", (sym, dt.date.today().isoformat()))


def sync(conn, syms, workers=6, force=False, fetcher=fetch) -> list[str]:
    """Tải BCTC cho các mã chưa có hoặc đã cũ hơn REFRESH_DAYS ngày (force: tải lại hết). Trả mã lỗi."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    old = (dt.date.today() - dt.timedelta(days=REFRESH_DAYS)).isoformat()
    need = [s for s in syms if force or not (r := conn.execute("SELECT fetched FROM fin_meta WHERE sym=?", (s,)).fetchone())
            or r[0] < old]
    errors = []

    def job(s):
        time.sleep(0.05)
        try:
            return s, fetcher(s)
        except Exception:
            return s, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(job, s) for s in need]):
            s, rows = f.result()
            if rows is None:
                errors.append(s); continue
            save(conn, s, rows)
    conn.commit()
    return errors


def load(conn, sym) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT fiscal, created, item, value FROM fin_quarter WHERE sym=?", (sym,))]


def _quarters_back(f: str, n: int) -> str:
    """Ngày cuối quý cách quý f đúng n quý về trước ('2026-09-30', 4 -> '2025-09-30')."""
    y, m = int(f[:4]), int(f[5:7])
    k = y * 4 + (m - 1) // 3 - n
    y2, q = divmod(k, 4)
    end = {0: "03-31", 1: "06-30", 2: "09-30", 3: "12-31"}[q]
    return f"{y2}-{end}"


def metrics_at(rows: list[dict], d: str | None = None) -> dict | None:
    """Chỉ số tại ngày d từ các báo cáo đã công bố (created ≤ d): LNST 4 quý (TTM), tăng trưởng so với 4 quý
    trước, ROE TTM (trên VCSH bình quân đầu/cuối kỳ), nợ vay/VCSH, doanh thu TTM. None nếu thiếu dữ liệu."""
    by = {}
    for r in rows:
        if d is None or r["created"] <= d:
            by.setdefault(r["fiscal"], {})[r["item"]] = r["value"]
    with_np = sorted(f for f, v in by.items() if "np" in v)
    if not with_np:
        return None
    last = with_np[-1]

    def ttm(end, item="np"):
        qs = [_quarters_back(end, i) for i in range(4)]
        vals = [by.get(q, {}).get(item) for q in qs]
        return sum(vals) if all(v is not None for v in vals) else None

    np_ttm, np_prev = ttm(last), ttm(_quarters_back(last, 4))
    eq_now, eq_prev = by[last].get("equity"), by.get(_quarters_back(last, 4), {}).get("equity")
    eq_avg = (eq_now + eq_prev) / 2 if eq_now and eq_prev else eq_now
    debt = sum(by[last].get(k) or 0 for k in ("debt_st", "debt_lt")) if any(k in by[last] for k in ("debt_st", "debt_lt")) else None
    growth = None
    if np_ttm is not None and np_prev:
        growth = round((np_ttm / np_prev - 1) * 100, 1) if np_prev > 0 else (None if np_ttm <= 0 else 999.0)
    return dict(fiscal=last, np_ttm=round(np_ttm, 1) if np_ttm is not None else None, np_growth=growth,
                roe=round(np_ttm / eq_avg * 100, 1) if np_ttm is not None and eq_avg and eq_avg > 0 else None,
                debt_equity=round(debt / eq_now, 2) if debt is not None and eq_now and eq_now > 0 else None,
                revenue_ttm=round(ttm(last, "revenue"), 1) if ttm(last, "revenue") is not None else None)
