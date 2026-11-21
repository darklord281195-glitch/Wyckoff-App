"""Backtest tín hiệu Wyckoff trên lịch sử. Mỗi phiên chạy lại analyse() + signals.build() chỉ với dữ liệu tới phiên đó,
khớp lệnh theo vùng vào của kế hoạch, rồi quản lý lệnh bằng positions.simulate(), tức đúng luật app dùng để cảnh báo.

Cách dùng (trong thư mục backend):
  .venv\\Scripts\\python -m app.backtest --backfill        # một lần: tải ~8 năm lịch sử mọi mã (vài phút)
  .venv\\Scripts\\python -m app.backtest                   # mọi mã từ 2019-06-01, ghi logs\\backtest-YYYYMMDD.csv
  .venv\\Scripts\\python -m app.backtest --symbols DPG,TCH --from 2022-01-01 --to 2024-12-31

Giới hạn: chỉ có mã đang niêm yết (mã đã hủy niêm yết không có trong dữ liệu nên kết quả có thể đẹp hơn thực tế);
giá đã điều chỉnh, KL có thể chưa điều chỉnh theo chia tách; giả định khớp đủ khối lượng, chỉ tính phí, không tính trượt giá.
"""
import argparse, bisect, csv, datetime as dt, time
from collections import Counter, defaultdict

from .config import LOG_DIR, MIN_LIQ_BIL
from .db import connect
from .core.data import get_ohlcv, sync_many
from .core.wyckoff import analyse, ANALYSIS_DAYS
from .core.market import traffic_light
from .core.positions import simulate
from .core import signals as sig
from .universe import universe, INDEX

HISTORY = 3000                          # số ngày lịch sử tải khi --backfill (~8 năm)
BUY_FEE, SELL_FEE = 0.0015, 0.0025      # phí môi giới 0,15% mỗi chiều; bán thêm thuế 0,1%
WAIT = 10                               # số phiên tối đa chờ khớp lệnh mua


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


def run_symbol(sym, R, IDX, start="0000", end="9999", orders=None):
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
        s = simulate(px, p["stop"], targets, R[f:])
        e = bisect.bisect_left(D, s["exits"][-1]["d"]) if not s["open"] else len(R) - 1
        value = (sum(z["frac"] * z["px"] for z in s["exits"]) + s["left"] * R[e]["c"]) * (1 - SELL_FEE)
        cost = px * (1 + BUY_FEE)
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


def report(trades, key, title):
    """In bảng thống kê các lệnh đã đóng, nhóm theo key(trade)."""
    g = defaultdict(list)
    for t in trades:
        if not t["open"]:
            g[key(t)].append(t)
    print(f"\n{title:<16}{'lệnh':>6}{'thắng%':>8}{'R TB':>7}{'lãi%TB':>8}{'phiên':>7}{'cắt lỗ%':>9}{'hết TG%':>9}{'chạm T1%':>10}")
    for k in sorted(g, key=str):
        xs = g[k]; n = len(xs)
        pc = lambda f: 100 * sum(1 for t in xs if f(t)) / n
        print(f"{str(k):<16}{n:>6}{pc(lambda t: t['R'] > 0):>8.0f}{sum(t['R'] for t in xs) / n:>7.2f}"
              f"{sum(t['ret'] for t in xs) / n:>8.1f}{sum(t['days'] for t in xs) / n:>7.0f}"
              f"{pc(lambda t: t['why'] == 'Cắt lỗ'):>9.0f}{pc(lambda t: t['why'] == 'Hết thời gian'):>9.0f}"
              f"{pc(lambda t: t['hit'] > 0):>10.0f}")


def ready_bucket(t):
    s = t["ready"]
    return "<60" if s < 60 else "60–69" if s < 70 else "70–79" if s < 80 else "≥80"


def main():
    ap = argparse.ArgumentParser(description="Backtest tín hiệu Wyckoff")
    ap.add_argument("--backfill", action="store_true", help=f"tải lại {HISTORY} ngày lịch sử cho các mã rồi thoát")
    ap.add_argument("--symbols", help="danh sách mã, mặc định toàn bộ HOSE+HNX + nhóm theo dõi + watchlist")
    ap.add_argument("--from", dest="start", default="2019-06-01")
    ap.add_argument("--to", dest="end", default="9999-12-31")
    a = ap.parse_args()
    conn = connect()
    syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else universe(conn)
    t0 = time.time()
    if a.backfill:
        err = sync_many(conn, syms + [INDEX], HISTORY, full=True)
        print(f"Đã tải {len(syms) + 1} mã trong {time.time() - t0:.0f} giây, lỗi {len(err)} {', '.join(err[:10])}")
        return
    IDX = get_ohlcv(conn, INDEX, HISTORY + 400, refresh=False)
    up, tot, orders, trades = defaultdict(int), defaultdict(int), Counter(), []
    for n, s in enumerate(syms, 1):
        R = get_ohlcv(conn, s, HISTORY + 400, refresh=False)
        add_breadth(R, up, tot)
        trades += run_symbol(s, R, IDX, a.start, a.end, orders)
        if n % 50 == 0:
            print(f"  {n}/{len(syms)} mã · {len(trades)} lệnh · {time.time() - t0:.0f} giây")
    light = lights(IDX, up, tot)
    for t in trades:
        t["light"] = light.get(t["sig_d"], "?")
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
    print("R = lời/lỗ sau phí chia rủi ro ban đầu (giá vào − cắt lỗ). R TB > 0 là có kỳ vọng dương.")
    report(trades, lambda t: "Tất cả", "Tổng")
    report(trades, lambda t: t["kind"], "Tín hiệu")
    report(trades, lambda t: t["light"], "Đèn lúc báo")
    report(trades, ready_bucket, "Điểm sẵn sàng")
    report(trades, lambda t: t["sig_d"][:4], "Năm")
    # shortcut: lọc sau khi chạy, nên lệnh bị ẩn vẫn chiếm chỗ "1 lệnh/mã"; đủ để so sánh luật, chưa phải mô phỏng đúng
    kept = [t for t in trades if t["kind"] not in sig.HIDE.get(t["light"], ())]
    report(kept, lambda t: "2019–23" if t["sig_d"] < "2024" else "2024–26", "Theo luật ẩn")
    print(f"\nChi tiết từng lệnh: {out}")


if __name__ == "__main__":
    main()
