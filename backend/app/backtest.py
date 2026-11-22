"""Backtest tín hiệu Wyckoff trên lịch sử. Mỗi phiên chạy lại analyse() + signals.build() chỉ với dữ liệu tới phiên đó,
khớp lệnh theo vùng vào của kế hoạch, rồi quản lý lệnh bằng positions.simulate(), tức đúng luật app dùng để cảnh báo.

Cách dùng (trong thư mục backend):
  .venv\\Scripts\\python -m app.backtest --backfill        # một lần: tải ~8 năm lịch sử mọi mã (vài phút)
  .venv\\Scripts\\python -m app.backtest                   # mọi mã từ 2019-06-01, ghi logs\\backtest-YYYYMMDD.csv
  .venv\\Scripts\\python -m app.backtest --symbols DPG,TCH --from 2022-01-01 --to 2024-12-31

Giới hạn: chỉ có mã đang niêm yết (mã đã hủy niêm yết không có trong dữ liệu nên kết quả có thể đẹp hơn thực tế);
giá đã điều chỉnh, KL có thể chưa điều chỉnh theo chia tách; giả định khớp đủ khối lượng.
Chi phí: phí + thuế (BUY_FEE/SELL_FEE) và trượt giá `--slip` mỗi chiều (mặc định 0,25%).
"""
import argparse, bisect, csv, datetime as dt, math, time
from collections import Counter, defaultdict

from .config import LOG_DIR, MIN_LIQ_BIL
from .db import connect
from .core.data import get_ohlcv, sync_many
from .core.wyckoff import analyse, ANALYSIS_DAYS
from .core.market import traffic_light
from .core.positions import simulate
from .core.plan import TIME_STOP
from .core.foreign import backfill_foreign, net_sum
from .core import fundamentals as fund
from .core import signals as sig
from .universe import universe, listing, INDEX

HISTORY = 3000                          # số ngày lịch sử tải khi --backfill (~8 năm)
BUY_FEE, SELL_FEE = 0.0015, 0.0025      # phí môi giới 0,15% mỗi chiều; bán thêm thuế 0,1%
WAIT = 10                               # số phiên tối đa chờ khớp lệnh mua
SLIP = 0.0025                           # trượt giá mỗi chiều (mua cao hơn, bán thấp hơn giá lý thuyết)
FEW = 30                                # nhóm ít hơn số lệnh này: kết quả chưa đáng tin


def _window(R, D, i):
    """R[j:i+1], j = phiên đầu tiên trong ANALYSIS_DAYS ngày trước D[i] (giống trim())."""
    since = (dt.date.fromisoformat(D[i]) - dt.timedelta(days=ANALYSIS_DAYS)).isoformat()
    return R[bisect.bisect_left(D, since, 0, i):i + 1]


def _liq(R, i):
    """GT TB20 (tỷ đồng/ngày) tại phiên i, cùng công thức analyse(): KL TB20 × giá đóng cửa."""
    return sum(r["v"] for r in R[i - 19:i + 1]) / 20 * R[i]["c"] if i >= 19 else 0.0


def _fill(R, i, p):
    """Khớp lệnh mua trong WAIT phiên sau phiên tín hiệu i -> (phiên khớp, giá khớp, phiên kết thúc chờ).
    Kế hoạch Phá trần: khớp giá đóng cửa của phiên đóng cửa trong vùng với KL ≥ 1,5×TB20 (điều kiện SOS).
    Còn lại: lệnh giới hạn ở entry_hi (mở cửa ≤ entry_hi khớp giá mở cửa; lùi về chạm entry_hi khớp entry_hi).
    Hủy khi giá xuống dưới cắt lỗ trước khi khớp."""
    lo, hi, stop = p["entry_lo"], p["entry_hi"], p["stop"]
    breakout = (p["kind"] or "").startswith("Phá trần")
    for k in range(i + 1, min(i + 1 + WAIT, len(R))):
        b = R[k]
        if breakout:
            if lo <= b["c"] <= hi and b["v"] >= 1.5 * sum(r["v"] for r in R[k - 20:k]) / 20:
                return k, b["c"], k
        elif b["o"] < stop:
            return None, None, k
        elif b["o"] <= hi:
            return k, b["o"], k
        elif b["l"] <= hi:
            return k, hi, k
        if b["c"] < stop:
            return None, None, k
    return None, None, min(i + WAIT, len(R) - 1)


def run_symbol(sym, R, IDX, start="0000", end="9999", orders=None, slip=SLIP, time_stop=TIME_STOP):
    """Các lệnh backtest của một mã; mỗi lúc chỉ một lệnh (đang chờ khớp hoặc đang giữ).
    R, IDX: OHLCV tăng dần, nên có đủ lịch sử trước `start` để phân tích. orders: Counter đếm lệnh đặt theo loại."""
    D, DI = [r["d"] for r in R], [r["d"] for r in IDX]
    trades, prev, i = [], None, max(bisect.bisect_left(D, start), 119)
    while i < len(R) and D[i] <= end:
        if _liq(R, i) < MIN_LIQ_BIL:                 # tín hiệu mua chỉ báo cho mã đủ thanh khoản: bỏ qua sớm cho nhanh
            prev = None; i += 1; continue
        k = bisect.bisect_right(DI, D[i]) - 1
        r = analyse(_window(R, D, i), _window(IDX, DI, k) if k >= 0 else None)
        sigs = [x for x in sig.build(sym, r, prev, False) if x["kind"] in sig.BUY] if r else []
        prev, p = r, (r or {}).get("plan") or {}
        if not sigs or not p.get("entry_hi") or not p.get("stop"):
            i += 1; continue
        x = min(sigs, key=lambda x: x["prio"])
        if orders is not None:
            orders[x["kind"]] += 1
        f, px, j = _fill(R, i, p)
        if f is None:
            i, prev = j + 1, None; continue
        targets = [t["price"] for t in p["targets"]]
        s = simulate(px, p["stop"], targets, R[f:], time_stop)
        e = bisect.bisect_left(D, s["exits"][-1]["d"]) if not s["open"] else len(R) - 1
        value = (sum(z["frac"] * z["px"] for z in s["exits"]) + s["left"] * R[e]["c"]) * (1 - SELL_FEE - slip)
        cost = px * (1 + BUY_FEE + slip)
        trades.append(dict(sym=sym, kind=x["kind"], plan=p["kind"], sig_d=D[i], entry_d=D[f], entry=round(px, 3),
                           stop=p["stop"], t1=targets[0] if targets else None, ready=p["ready"]["score"], rr=p.get("rr"),
                           exit_d=D[e], why="đang giữ" if s["open"] else s["exits"][-1]["why"], hit=s["hit"],
                           days=e - f, R=round((value - cost) / max(px - p["stop"], px * 1e-3), 2),
                           ret=round((value / cost - 1) * 100, 2), open=s["open"]))
        i, prev = e + 1, None
    return trades


def add_breadth(R, up, tot):
    """Cộng dồn độ rộng theo ngày: tot = số mã đủ thanh khoản, up = số mã trong đó đóng cửa trên MA50."""
    for i in range(49, len(R)):
        if _liq(R, i) >= MIN_LIQ_BIL:
            d = R[i]["d"]; tot[d] += 1
            up[d] += R[i]["c"] > sum(r["c"] for r in R[i - 49:i + 1]) / 50


def lights(IDX, up, tot):
    """{ngày: đèn} theo xu hướng VNINDEX + độ rộng; không dùng ngưỡng cố định .env (chỉ hợp với mức điểm hiện tại)."""
    C, out = [r["c"] for r in IDX], {}
    for i in range(199, len(IDX)):
        d = IDX[i]["d"]
        b = round(100 * up[d] / tot[d]) if tot[d] >= 30 else None
        out[d] = traffic_light(dict(c=C[i], ma50=sum(C[i - 49:i + 1]) / 50, ma200=sum(C[i - 199:i + 1]) / 200),
                               b, fixed=False)["light"]
    return out


def stats(xs):
    """Thống kê một nhóm lệnh đã đóng. ci_lo/ci_hi: khoảng tin cậy 95% của R TB (xấp xỉ chuẩn, ±1,96·sd/√n)."""
    n = len(xs)
    pc = lambda f: round(100 * sum(1 for t in xs if f(t)) / n, 1)
    avg = sum(t["R"] for t in xs) / n
    sd = math.sqrt(sum((t["R"] - avg) ** 2 for t in xs) / (n - 1)) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
    return dict(n=n, win=pc(lambda t: t["R"] > 0), avg_r=round(avg, 2), ci_lo=round(avg - half, 2), ci_hi=round(avg + half, 2),
                ret=round(sum(t["ret"] for t in xs) / n, 2), avg_days=round(sum(t["days"] for t in xs) / n, 1),
                stop=pc(lambda t: t["why"] == "Cắt lỗ"), timeout=pc(lambda t: t["why"] == "Hết thời gian"),
                hit_t1=pc(lambda t: t["hit"] > 0))


def groups(trades, key):
    """{nhóm: stats} của các lệnh đã đóng, nhóm theo key(trade)."""
    g = defaultdict(list)
    for t in trades:
        if not t["open"]:
            g[key(t)].append(t)
    return {k: stats(v) for k, v in g.items()}


def report(trades, key, title):
    """In bảng thống kê các lệnh đã đóng, nhóm theo key(trade). * = nhóm dưới FEW lệnh."""
    g = groups(trades, key)
    print(f"\n{title:<16}{'lệnh':>7}{'thắng%':>8}{'R TB':>7}{'KTC95% R':>15}{'lãi%TB':>8}{'phiên':>7}"
          f"{'cắt lỗ%':>9}{'hết TG%':>9}{'chạm T1%':>10}")
    for k in sorted(g, key=str):
        s = g[k]
        ci = f"{s['ci_lo']:+.2f}…{s['ci_hi']:+.2f}" if s["n"] > 1 else "–"
        print(f"{str(k):<16}{s['n']:>6}{'*' if s['n'] < FEW else ' '}{s['win']:>8.0f}{s['avg_r']:>7.2f}{ci:>15}"
              f"{s['ret']:>8.1f}{s['avg_days']:>7.0f}{s['stop']:>9.0f}{s['timeout']:>9.0f}{s['hit_t1']:>10.0f}")


def plan_group(t):
    """Loại kế hoạch rút gọn: 'Phá trần (SOS)' -> 'Phá trần' (API khớp theo tiền tố plan.kind)."""
    return (t["plan"] or "?").split(" (")[0]


def save_stats(conn, trades, period, slip):
    """Ghi thống kê theo loại kế hoạch (và 'Tất cả') vào backtest_stats để trang mã hiện cạnh kịch bản."""
    rows = groups(trades, plan_group)
    closed = [t for t in trades if not t["open"]]
    if closed:
        rows["Tất cả"] = stats(closed)
    conn.execute("DELETE FROM backtest_stats")
    conn.executemany(
        "INSERT INTO backtest_stats(plan,n,hit_t1,stop,timeout,avg_r,ci_lo,ci_hi,avg_days,period,slip,updated) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,date('now','localtime'))",
        [(k, s["n"], s["hit_t1"], s["stop"], s["timeout"], s["avg_r"], s["ci_lo"], s["ci_hi"], s["avg_days"], period, slip)
         for k, s in rows.items()])
    conn.commit()


def ready_bucket(t):
    s = t["ready"]
    return "<60" if s < 60 else "60–69" if s < 70 else "70–79" if s < 80 else "≥80"


def add_sector_rs(R, idx_c, icb, acc):
    """Cộng dồn RS20 theo (ngành, ngày) cho các phiên mã đủ thanh khoản; cùng công thức rs_vs_index (% so VNINDEX)."""
    if not icb:
        return
    for i in range(20, len(R)):
        d, d0 = R[i]["d"], R[i - 20]["d"]
        if d in idx_c and d0 in idx_c and _liq(R, i) >= MIN_LIQ_BIL:
            acc[(icb, d)].append((R[i]["c"] / R[i - 20]["c"] - idx_c[d] / idx_c[d0]) * 100)


def sector_medians(acc, min_n=3):
    """{(ngành, ngày): trung vị RS20} cho nhóm có ít nhất min_n mã."""
    out = {}
    for k, xs in acc.items():
        if len(xs) >= min_n:
            xs = sorted(xs); m = len(xs) // 2
            out[k] = round(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2, 2)
    return out


def collect(conn, syms, start, end, slip=SLIP, time_stops=(TIME_STOP,), log=print):
    """({time_stop: [lệnh]}, Counter lệnh đặt, {ngày: đèn}): chạy backtest mọi mã; mỗi lệnh gắn đèn, khối ngoại 10 phiên và RS20 ngành lúc báo.
    Nhiều time_stop thì chạy lại run_symbol cho từng giá trị (điểm vào giống nhau, chỉ khác luật thoát)."""
    t0 = time.time()
    IDX = get_ohlcv(conn, INDEX, HISTORY + 400, refresh=False)
    idx_c = {r["d"]: r["c"] for r in IDX}
    lst = listing(conn)
    up, tot, sec, orders = defaultdict(int), defaultdict(int), defaultdict(list), Counter()
    out = {ts: [] for ts in time_stops}
    for n, s in enumerate(syms, 1):
        R = get_ohlcv(conn, s, HISTORY + 400, refresh=False)
        add_breadth(R, up, tot)
        add_sector_rs(R, idx_c, (lst.get(s) or {}).get("icb"), sec)
        for j, ts in enumerate(time_stops):
            out[ts] += run_symbol(s, R, IDX, start, end, orders if j == 0 else None, slip, ts)
        if n % 50 == 0:
            log(f"  {n}/{len(syms)} mã · {len(out[time_stops[0]])} lệnh · {time.time() - t0:.0f} giây")
    light, med = lights(IDX, up, tot), sector_medians(sec)
    for trades in out.values():
        for t in trades:
            t["light"] = light.get(t["sig_d"], "?")
            t["fx10"] = net_sum(conn, t["sym"], t["sig_d"])
            t["sector_rs20"] = med.get(((lst.get(t["sym"]) or {}).get("icb"), t["sig_d"]))
    return out, orders, light


PERIODS = (("2019–23", lambda t: t["sig_d"] < "2024"), ("2024–26", lambda t: t["sig_d"] >= "2024"), ("Tất cả", lambda t: True))


def compare(trades, name, keep, has=lambda t: True):
    """In so sánh lệnh giữ lại / bỏ đi theo một bộ lọc, tách 2019–23 và 2024–26.
    has(t) = lệnh có đủ dữ liệu cho bộ lọc này (vd có khối ngoại); lệnh thiếu bị loại khỏi so sánh."""
    closed = [t for t in trades if not t["open"]]
    usable = [t for t in closed if has(t)]
    miss = len(closed) - len(usable)
    print(f"\n{name}" + (f"  (bỏ {miss} lệnh thiếu dữ liệu)" if miss else ""))
    print(f"  {'giai đoạn':<10}{'':<9}{'lệnh':>7}{'thắng%':>8}{'R TB':>7}{'KTC95% R':>16}")
    for pname, pf in PERIODS:
        for label, sel in (("giữ lại", True), ("bỏ đi", False)):
            xs = [t for t in usable if pf(t) and bool(keep(t)) == sel]
            if not xs:
                print(f"  {pname:<10}{label:<9}{0:>7}"); continue
            s = stats(xs)
            ci = f"{s['ci_lo']:+.2f}…{s['ci_hi']:+.2f}" if s["n"] > 1 else "–"
            print(f"  {pname:<10}{label:<9}{s['n']:>6}{'*' if s['n'] < FEW else ' '}{s['win']:>8.0f}{s['avg_r']:>7.2f}{ci:>16}")


def run_compare(conn, syms, a, slip):
    """Kiểm chứng các bộ lọc mới so với toàn bộ lệnh và luật ẩn hiện tại; ghi logs/compare-YYYYMMDD.csv."""
    tss = sorted({int(x) for x in a.time_stop.split(",")} | {TIME_STOP})
    out, _, _ = collect(conn, syms, a.start, a.end, slip, tuple([TIME_STOP] + [x for x in tss if x != TIME_STOP]))
    trades = out[TIME_STOP]
    if not trades:
        print("Không có lệnh nào (đã chạy --backfill chưa?)"); return
    fin = {}
    for t in trades:                       # chỉ số cơ bản tại ngày báo, chỉ từ báo cáo đã công bố trước đó
        rows = fin.setdefault(t["sym"], fund.load(conn, t["sym"]))
        m = fund.metrics_at(rows, t["sig_d"]) or {}
        t["np_growth"], t["roe"] = m.get("np_growth"), m.get("roe")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"compare-{dt.date.today():%Y%m%d}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0])); w.writeheader(); w.writerows(trades)
    print(f"So sánh bộ lọc trên {len(trades)} lệnh (trượt giá {a.slip:g}%/chiều). "
          "Bộ lọc đáng dùng: 'giữ lại' tốt hơn 'bỏ đi' ở CẢ 2019–23 lẫn 2024–26. * = dưới 30 lệnh.")
    hidden = lambda t: t["kind"] in sig.HIDE.get(t["light"], ())
    green, fx, sec = (lambda t: t["light"] == "green"), (lambda t: t["fx10"] > 0), (lambda t: t["sector_rs20"] > 0)
    has_fx, has_sec = (lambda t: t["fx10"] is not None), (lambda t: t["sector_rs20"] is not None)
    compare(trades, "0) Luật ẩn hiện tại (đỏ: ẩn mọi lệnh mua; vàng: ẩn LPS, D sớm)", lambda t: not hidden(t))
    compare(trades, "a) Chỉ mua khi đèn xanh", green)
    compare(trades, "b) Khối ngoại mua ròng 10 phiên > 0", fx, has_fx)
    compare(trades, "c) Ngành mạnh hơn VNINDEX (trung vị RS20 ngành > 0)", sec, has_sec)
    compare(trades, "e1) Đèn xanh + ngành mạnh", lambda t: green(t) and sec(t), has_sec)
    compare(trades, "e2) Đèn xanh + khối ngoại mua ròng", lambda t: green(t) and fx(t), has_fx)
    compare(trades, "e3) Luật ẩn hiện tại + ngành mạnh", lambda t: not hidden(t) and sec(t), has_sec)
    grow, roe = (lambda t: t["np_growth"] > 0), (lambda t: t["roe"] > 10)
    has_g, has_r = (lambda t: t["np_growth"] is not None), (lambda t: t["roe"] is not None)
    compare(trades, "f1) LNST 4 quý tăng trưởng > 0 (so với 4 quý trước)", grow, has_g)
    compare(trades, "f2) ROE 4 quý > 10%", roe, has_r)
    compare(trades, "f3) Tăng trưởng > 0 và ROE > 10%", lambda t: grow(t) and roe(t), lambda t: has_g(t) and has_r(t))
    compare(trades, "f4) Luật ẩn hiện tại + f3", lambda t: not hidden(t) and grow(t) and roe(t),
            lambda t: has_g(t) and has_r(t))
    print("\nd) Cắt lỗ theo thời gian (cùng điểm vào, chỉ khác số phiên chờ chạm T1)")
    print(f"  {'phiên':<8}{'giai đoạn':<10}{'lệnh':>7}{'thắng%':>8}{'R TB':>7}{'KTC95% R':>16}{'phiên giữ':>11}")
    for ts in tss:
        for pname, pf in PERIODS:
            xs = [t for t in out[ts] if not t["open"] and pf(t)]
            if xs:
                s = stats(xs)
                print(f"  {ts:<8}{pname:<10}{s['n']:>6} {s['win']:>8.0f}{s['avg_r']:>7.2f}"
                      f"{s['ci_lo']:+9.2f}…{s['ci_hi']:+.2f}{s['avg_days']:>9.0f}")
    print(f"\nChi tiết từng lệnh (kèm đèn, khối ngoại, RS ngành): {path}")


def main():
    ap = argparse.ArgumentParser(description="Backtest tín hiệu Wyckoff")
    ap.add_argument("--backfill", action="store_true", help=f"tải lại {HISTORY} ngày lịch sử cho các mã rồi thoát")
    ap.add_argument("--backfill-foreign", action="store_true",
                    help="tải ~8 năm khối ngoại cho các mã từng có GT ≥ MIN_LIQ_BIL rồi thoát (cho --compare)")
    ap.add_argument("--backfill-fundamentals", action="store_true",
                    help="tải BCTC quý (LNST, VCSH, doanh thu, nợ vay) cho các mã từng có GT ≥ MIN_LIQ_BIL rồi thoát")
    ap.add_argument("--compare", action="store_true", help="kiểm chứng các bộ lọc mới (đèn xanh, khối ngoại, ngành, cắt lỗ thời gian)")
    ap.add_argument("--time-stop", default="15,20,30", help="cùng --compare: các số phiên cắt lỗ thời gian để so")
    ap.add_argument("--portfolio", action="store_true",
                    help="backtest cấp danh mục (vốn giới hạn, nhiều lệnh) so với mua-giữ VNINDEX và chỉ theo đèn")
    ap.add_argument("--symbols", help="danh sách mã, mặc định toàn bộ HOSE+HNX + nhóm theo dõi + watchlist")
    ap.add_argument("--from", dest="start", default="2019-06-01")
    ap.add_argument("--to", dest="end", default="9999-12-31")
    ap.add_argument("--slip", type=float, default=SLIP * 100, help="trượt giá mỗi chiều, %% (mặc định 0,25)")
    a = ap.parse_args()
    slip = a.slip / 100
    conn = connect()
    syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else universe(conn)
    t0 = time.time()
    if a.backfill:
        err = sync_many(conn, syms + [INDEX], HISTORY, full=True)
        print(f"Đã tải {len(syms) + 1} mã trong {time.time() - t0:.0f} giây, lỗi {len(err)} {', '.join(err[:10])}")
        return
    if a.backfill_foreign:
        liquid = [s for s in syms if any(_liq(R, i) >= MIN_LIQ_BIL for R in [get_ohlcv(conn, s, HISTORY + 400, refresh=False)]
                                         for i in range(19, len(R), 5))]
        err = backfill_foreign(conn, liquid)
        print(f"Đã tải khối ngoại {len(liquid)} mã trong {time.time() - t0:.0f} giây, lỗi {len(err)} {', '.join(err[:10])}")
        return
    if a.backfill_fundamentals:
        liquid = [s for s in syms if any(_liq(R, i) >= MIN_LIQ_BIL for R in [get_ohlcv(conn, s, HISTORY + 400, refresh=False)]
                                         for i in range(19, len(R), 5))]
        err = fund.sync(conn, liquid, force=True)
        n = conn.execute("SELECT count(DISTINCT sym), count(*) FROM fin_quarter").fetchone()
        print(f"Đã tải BCTC {len(liquid)} mã trong {time.time() - t0:.0f} giây ({n[0]} mã có số liệu, {n[1]} dòng), "
              f"lỗi {len(err)} {', '.join(err[:10])}")
        return
    if a.compare:
        run_compare(conn, syms, a, slip); return
    if a.portfolio:
        from . import portfolio_bt
        out, _, light = collect(conn, syms, a.start, a.end, slip)
        if not out[TIME_STOP]:
            print("Không có lệnh nào (đã chạy --backfill chưa?)"); return
        res = portfolio_bt.run(conn, out[TIME_STOP], get_ohlcv(conn, INDEX, HISTORY + 400, refresh=False), light)
        portfolio_bt.print_report(res)
        print("\nĐã lưu kết quả (trang Kết quả trên web).")
        return
    out, orders, _ = collect(conn, syms, a.start, a.end, slip)
    trades = out[TIME_STOP]
    if not trades:
        print("Không có lệnh nào (đã chạy --backfill chưa?)"); return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / f"backtest-{dt.date.today():%Y%m%d}.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:          # utf-8-sig để Excel đọc đúng tiếng Việt
        w = csv.DictWriter(f, fieldnames=list(trades[0])); w.writeheader(); w.writerows(trades)
    first, last = min(t["sig_d"] for t in trades), max(t["sig_d"] for t in trades)
    print(f"\nBacktest {len(syms)} mã, tín hiệu {first} → {last}, {len(trades)} lệnh "
          f"({sum(t['open'] for t in trades)} đang giữ, không tính vào bảng) · {time.time() - t0:.0f} giây")
    print("Tỷ lệ khớp: " + " · ".join(f"{k} {100 * sum(t['kind'] == k for t in trades) / v:.0f}% của {v}"
                                     for k, v in orders.most_common()))
    print(f"R = lời/lỗ sau phí + trượt giá {a.slip:g}%/chiều, chia rủi ro ban đầu (giá vào − cắt lỗ). "
          "R TB > 0 là có kỳ vọng dương.")
    print(f"KTC95% R: R TB thật nằm trong khoảng này với độ tin cậy ~95%; khoảng chứa 0 = chưa chắc có lợi thế. "
          f"* = dưới {FEW} lệnh.")
    report(trades, lambda t: "Tất cả", "Tổng")
    report(trades, lambda t: t["kind"], "Tín hiệu")
    report(trades, plan_group, "Kế hoạch")
    report(trades, lambda t: t["light"], "Đèn lúc báo")
    report(trades, ready_bucket, "Điểm sẵn sàng")
    report(trades, lambda t: t["sig_d"][:4], "Năm")
    # shortcut: lọc sau khi chạy, nên lệnh bị ẩn vẫn chiếm chỗ "1 lệnh/mã"; đủ để so sánh luật, chưa phải mô phỏng đúng
    kept = [t for t in trades if t["kind"] not in sig.HIDE.get(t["light"], ())]
    report(kept, lambda t: "2019–23" if t["sig_d"] < "2024" else "2024–26", "Theo luật ẩn")
    print(f"\nChi tiết từng lệnh: {out}")
    if not a.symbols:          # chỉ ghi thống kê cho trang mã khi chạy đủ mọi mã (mẫu nhỏ dễ sai lệch)
        save_stats(conn, trades, f"{first[:4]}–{last[:4]}", a.slip)
        print("Đã lưu thống kê theo loại kế hoạch (trang mã hiện cạnh kịch bản).")


if __name__ == "__main__":
    main()
