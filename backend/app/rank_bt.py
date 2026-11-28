"""Kiểm chứng lịch sử Top tiềm năng: đầu mỗi tháng chấm lại mọi mã đủ thanh khoản (chỉ dữ liệu tới phiên đó, cùng hàm
rank.factors / rank.pct_scores như bản chạy thật), so lợi nhuận `hold` phiên sau của top N với nhóm được xếp (bỏ
rank.EXCLUDE_TAGS), mọi mã đủ thanh khoản và VNINDEX. Có lợi thế khi top N hơn TB mọi mã đủ thanh khoản ở CẢ 2019–23
lẫn 2024–26.

Cách dùng (trong thư mục backend):
  .venv\\Scripts\\python -m app.rank_bt                    # mọi mã từ 2019-06-01, ghi bảng rank_bt + logs\\rank-bt-YYYYMMDD.csv
  .venv\\Scripts\\python -m app.rank_bt --symbols TCH,DPG --from 2024-01-01 --to 2024-12-31
  .venv\\Scripts\\python -m app.rank_bt --daily            # lấp snapshot rank_daily cho các phiên đã quét (chạy 1 lần)

Giới hạn: chỉ có mã đang niêm yết (survivorship, kết quả có thể đẹp hơn thực tế); chưa trừ phí và trượt giá;
điểm tính ở giá đóng cửa phiên đầu tháng, mua giá mở cửa phiên sau.
"""
import argparse, bisect, csv, datetime as dt, time
from collections import defaultdict

from .config import LOG_DIR, MIN_LIQ_BIL
from .db import connect
from .core.data import get_ohlcv
from .core.wyckoff import analyse
from .core import rank as rank_mod
from .backtest import HISTORY, _window, _liq
from .universe import universe, listing, INDEX
from . import health

MIN_E = 10                      # tháng có ít mã được xếp hơn: không tính IC
PERIODS = (("2019–23", lambda d: d < "2024"), ("2024–26", lambda d: d >= "2024"), ("Tất cả", lambda d: True))


def fwd(R, i, hold):
    """Lợi nhuận % từ giá mở cửa phiên sau phiên chấm (i+1) tới giá đóng cửa phiên i+hold; None nếu chưa đủ dữ liệu."""
    if i + hold >= len(R) or i + 1 >= len(R) or not R[i + 1]["o"]:
        return None
    return round((R[i + hold]["c"] / R[i + 1]["o"] - 1) * 100, 2)


def _ranks(xs):
    """Hạng trung bình (1..n) khi trùng giá trị."""
    idx = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and xs[idx[j + 1]] == xs[idx[i]]:
            j += 1
        for k in range(i, j + 1):
            out[idx[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a, b):
    """Tương quan hạng Spearman (Pearson trên hạng trung bình); None nếu < 3 cặp hoặc một bên không đổi."""
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return cov / (va * vb) ** 0.5 if va and vb else None


def month_starts(IDX, start, end, hold):
    """Phiên giao dịch đầu mỗi tháng (theo VNINDEX) trong [start, end], phía sau còn ≥ hold+1 phiên."""
    out, seen = [], set()
    for i, r in enumerate(IDX):
        m = r["d"][:7]
        if m in seen:
            continue
        seen.add(m)
        if start <= r["d"] <= end and i + hold + 1 < len(IDX):
            out.append(r["d"])
    return out


def collect(conn, syms, start, end, hold=20, log=print):
    """Các lượt chấm: dict(date, sym, tag, excluded, eligible, dry, vol, ready, fwd20, fwd60) + {ngày: lợi nhuận
    VNINDEX}. Điểm (total, p_dry, p_vol, p_ready) được tính theo từng tháng trong months()."""
    t0 = time.time()
    IDX = get_ohlcv(conn, INDEX, HISTORY + 400, refresh=False)
    DI = [r["d"] for r in IDX]
    days = month_starts(IDX, start, end, hold)
    vni = {d: fwd(IDX, DI.index(d), hold) for d in days}
    lst = listing(conn)
    out = []
    for n, s in enumerate(syms, 1):
        R = get_ohlcv(conn, s, HISTORY + 400, refresh=False)
        if len(R) < 120:
            continue
        D = [r["d"] for r in R]
        floor = (lst.get(s) or {}).get("floor") or "UPCOM"
        for d in days:
            i = bisect.bisect_left(D, d)
            if i >= len(D) or D[i] != d or i < 119 or _liq(R, i) < MIN_LIQ_BIL:
                continue
            k = bisect.bisect_right(DI, d) - 1
            r = analyse(_window(R, D, i), _window(IDX, DI, k), floor)
            if not r:
                continue
            since = (dt.date.fromisoformat(d) - dt.timedelta(days=500)).isoformat()
            bars = R[bisect.bisect_right(D, since, 0, i):i + 1]
            out.append(dict(date=d, sym=s, tag=r.get("tag"), excluded=int(r.get("tag") in rank_mod.EXCLUDE_TAGS),
                            eligible=int(rank_mod.eligible(r)), **rank_mod.factors(r, bars),
                            fwd20=fwd(R, i, hold), fwd60=fwd(R, i, 60), top=0))
        if n % 100 == 0:
            log(f"  {n}/{len(syms)} mã · {len(out)} lượt chấm · {time.time() - t0:.0f} giây")
    return out, vni


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def months(picks, vni, top_n=10):
    """Mỗi tháng: chấm phần trăm trong nhóm được xếp (E = bỏ EXCLUDE_TAGS); lợi nhuận TB của top N, của E, mọi mã đủ
    thanh khoản, VNINDEX; IC Spearman giữa điểm (và từng thành phần) với fwd20 trong E (|E| ≥ MIN_E).
    Ghi total / p_dry / p_vol / p_ready và top=1 vào các lượt chấm."""
    by = defaultdict(list)
    for x in picks:
        if x["fwd20"] is not None:
            by[x["date"]].append(x)
    out = []
    for d in sorted(by):
        xs = by[d]
        E = [x for x in xs if not x["excluded"]]
        if not E:
            continue
        for x, sc in zip(E, rank_mod.pct_scores(E)):
            x.update(total=sc["total"], p_dry=sc["dry"], p_vol=sc["vol"], p_ready=sc["ready"])
        E.sort(key=lambda x: (-x["total"], -x["p_dry"], x["sym"]))
        top = E[:top_n]
        for x in top:
            x["top"] = 1
        ic = {}
        for k, key in (("ic", "total"), ("ic_w", "p_dry"), ("ic_t", "p_vol"), ("ic_f", "p_ready")):
            ic[k] = spearman([x[key] for x in E], [x["fwd20"] for x in E]) if len(E) >= MIN_E else None
        out.append(dict(date=d, n_e=len(E), top_ret=_mean(x["fwd20"] for x in top), elig_ret=_mean(x["fwd20"] for x in E),
                        liq_ret=_mean(x["fwd20"] for x in xs), vni_ret=vni.get(d),
                        wins=sum(x["fwd20"] > 0 for x in top), n_top=len(top), **ic))
    return out


def summarize(ms, top_n, hold):
    """{giai đoạn: chỉ số} (lợi nhuận %/hold phiên, TB các tháng; beat_pct = % tháng top thắng TB mọi mã đủ thanh
    khoản; top_win = % lượt chọn lãi; ic_w / ic_t / ic_f = IC của cung cạn / biến động thấp / sẵn sàng)."""
    res = {}
    for name, f in PERIODS:
        xs = [m for m in ms if f(m["date"])]
        if not xs:
            continue
        ic = lambda k: (round(sum(m[k] for m in xs if m[k] is not None) / n, 3)
                        if (n := sum(m[k] is not None for m in xs)) else None)
        res[name] = dict(months=len(xs), top_n=top_n, hold=hold, top_ret=_mean(m["top_ret"] for m in xs),
                         elig_ret=_mean(m["elig_ret"] for m in xs), liq_ret=_mean(m["liq_ret"] for m in xs),
                         vni_ret=_mean(m["vni_ret"] for m in xs),
                         beat_pct=round(100 * sum(m["top_ret"] > m["liq_ret"] for m in xs) / len(xs), 1),
                         top_win=round(100 * sum(m["wins"] for m in xs) / max(sum(m["n_top"] for m in xs), 1), 1),
                         ic=ic("ic"), ic_w=ic("ic_w"), ic_t=ic("ic_t"), ic_f=ic("ic_f"))
    return res


COLS = ("months", "top_n", "hold", "top_ret", "elig_ret", "liq_ret", "vni_ret", "beat_pct", "top_win", "ic", "ic_w", "ic_t", "ic_f")


def save(conn, res):
    conn.execute("DELETE FROM rank_bt")
    conn.executemany(f"INSERT INTO rank_bt(period,{','.join(COLS)},updated) VALUES (?,{','.join('?' * len(COLS))},"
                     "date('now','localtime'))", [(k, *(v[c] for c in COLS)) for k, v in res.items()])
    conn.commit()


def print_report(res, hold, top_n):
    f = lambda x, d=2: "–" if x is None else f"{x:+.{d}f}"
    print(f"\nLợi nhuận TB {hold} phiên (%, chưa trừ phí), mua giá mở cửa phiên sau ngày chấm đầu tháng:")
    print(f"{'giai đoạn':<10}{'tháng':>6}{'top' + str(top_n):>8}{'nhóm xếp':>9}{'đủ TK':>8}{'VNI':>8}{'thắng%':>8}"
          f"{'lãi%':>7}{'IC':>8}{'IC cạn':>8}{'IC b.đ':>8}{'IC s.s':>8}")
    for k, v in res.items():
        print(f"{k:<10}{v['months']:>6}{f(v['top_ret']):>8}{f(v['elig_ret']):>9}{f(v['liq_ret']):>8}{f(v['vni_ret']):>8}"
              f"{v['beat_pct']:>8.0f}{v['top_win']:>7.0f}{f(v['ic'], 3):>8}{f(v['ic_w'], 3):>8}{f(v['ic_t'], 3):>8}"
              f"{f(v['ic_f'], 3):>8}")
    print("nhóm xếp = mã đủ thanh khoản trừ B/C, SOS hỏng, dưới hỗ trợ · thắng% = % số tháng top thắng TB mọi mã đủ "
          "thanh khoản · lãi% = % lượt chọn có lời · IC = tương quan hạng điểm với lợi nhuận (> 0,05 là có ích). "
          "Có lợi thế khi top > đủ TK ở CẢ 2019–23 lẫn 2024–26.")


def main():
    ap = argparse.ArgumentParser(description="Kiểm chứng lịch sử Top tiềm năng")
    ap.add_argument("--from", dest="start", default="2019-06-01")
    ap.add_argument("--to", dest="end", default="9999-12-31")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--hold", type=int, default=20)
    ap.add_argument("--symbols", help="danh sách mã, mặc định toàn bộ (chỉ chạy đủ mọi mã mới ghi bảng rank_bt)")
    ap.add_argument("--daily", action="store_true", help="lấp snapshot rank_daily cho các phiên đã quét rồi thoát")
    a = ap.parse_args()
    conn = connect()
    t0 = time.time()
    if a.daily:
        n = rank_mod.backfill_daily(conn)
        print(f"Đã lưu Top tiềm năng {n} phiên trong {time.time() - t0:.0f} giây")
        return
    started = health.now_vn().isoformat(timespec="seconds")
    try:
        syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else universe(conn)
        picks, vni = collect(conn, syms, a.start, a.end, a.hold)
        ms = months(picks, vni, a.top)
        res = summarize(ms, a.top, a.hold)
        if not res:
            print("Không có tháng nào đủ dữ liệu (đã chạy app.backtest --backfill chưa?)")
            if not a.symbols:
                health.record(conn, "rank_bt", started, "error", dict(error="không có dữ liệu"))
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"rank-bt-{dt.date.today():%Y%m%d}.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["date", "sym", "tag", "excluded", "eligible", "dry", "vol", "ready", "total",
                                              "p_dry", "p_vol", "p_ready", "fwd20", "fwd60", "top"])
            w.writeheader(); w.writerows(picks)
        print(f"Kiểm chứng {len(syms)} mã, {len(ms)} tháng, {len(picks)} lượt chấm · {time.time() - t0:.0f} giây")
        print_report(res, a.hold, a.top)
        print(f"\nChi tiết từng lượt chấm: {path}")
        print("Giới hạn: chỉ mã đang niêm yết, chưa trừ phí và trượt giá (~1%/lần mua–bán).")
        if not a.symbols:
            save(conn, res)
            health.record(conn, "rank_bt", started, "ok", dict(months=len(ms), picks=len(picks),
                                                                 seconds=round(time.time() - t0)))
            print("Đã lưu kết quả (thẻ Kiểm chứng lịch sử trên trang Top 10).")
    except Exception as e:
        if not a.symbols:
            health.record(conn, "rank_bt", started, "error", dict(error=str(e)[:500]))
        raise


if __name__ == "__main__":
    main()
