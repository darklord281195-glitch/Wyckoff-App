"""Chấm điểm tín hiệu thật (forward test): mỗi tín hiệu mua app đã báo được theo dõi bằng đúng luật backtest
(khớp lệnh theo vùng vào trong WAIT phiên, rồi bán theo positions.simulate), tính R sau phí + trượt giá.
Khác backtest ở chỗ chỉ dùng tín hiệu đã thực sự báo, nên sau vài tháng là bằng chứng không thể "chỉnh cho đẹp"."""
import bisect
import json

from .data import get_ohlcv
from .positions import simulate
from . import signals as sig


def score(conn, live_only=True, wait=None, slip=None, fees=None):
    """Danh sách tín hiệu mua lần đầu (is_new=1) kèm kết quả theo luật + tổng hợp.
    live_only: chỉ tín hiệu báo thật lúc quét thường (replay=0), bỏ các phiên tạo lại bằng scan --from."""
    from .. import backtest as bt                       # import muộn: backtest import nhiều module app
    wait = wait or bt.WAIT
    slip = bt.SLIP if slip is None else slip
    buy_fee, sell_fee = fees or (bt.BUY_FEE, bt.SELL_FEE)
    q = (f"SELECT date, sym, kind, replay FROM signals WHERE is_new=1 AND kind IN ({','.join('?' * len(sig.BUY))})"
         + (" AND replay=0" if live_only else "") + " ORDER BY date, sym")
    items, cache = [], {}
    for s in conn.execute(q, sig.BUY).fetchall():
        row = conn.execute("SELECT data FROM scan_results WHERE date=? AND sym=?", (s["date"], s["sym"])).fetchone()
        p = (json.loads(row[0]).get("plan") or {}) if row else {}
        it = dict(date=s["date"], sym=s["sym"], kind=s["kind"], replay=bool(s["replay"]), plan=p.get("kind"),
                  entry_lo=p.get("entry_lo"), entry_hi=p.get("entry_hi"), stop=p.get("stop"),
                  status="không có kế hoạch", entry_d=None, entry=None, exit_d=None, why=None, R=None)
        if p.get("entry_hi") and p.get("stop"):
            R = cache.setdefault(s["sym"], get_ohlcv(conn, s["sym"], 10000, refresh=False))
            D = [r["d"] for r in R]
            i = bisect.bisect_right(D, s["date"]) - 1
            if i >= 0 and D[i] == s["date"]:
                f, px, j = bt._fill(R, i, p)
                if f is None:
                    pending = j == len(R) - 1 and j - i < wait and R[j]["c"] >= p["stop"]
                    it["status"] = "chờ khớp" if pending else "không khớp"
                else:
                    targets = [t["price"] for t in p.get("targets", [])]
                    r = simulate(px, p["stop"], targets, R[f:])
                    e = bisect.bisect_left(D, r["exits"][-1]["d"]) if not r["open"] else len(R) - 1
                    value = (sum(z["frac"] * z["px"] for z in r["exits"]) + r["left"] * R[e]["c"]) * (1 - sell_fee - slip)
                    cost = px * (1 + buy_fee + slip)
                    it.update(status="đang giữ" if r["open"] else "đã đóng", entry_d=D[f], entry=round(px, 3),
                              exit_d=None if r["open"] else D[e], why=None if r["open"] else r["exits"][-1]["why"],
                              R=round((value - cost) / max(px - p["stop"], px * 1e-3), 2))
        items.append(it)
    closed = [x for x in items if x["status"] == "đã đóng"]
    filled = [x for x in items if x["R"] is not None]
    decided = [x for x in items if x["status"] in ("đã đóng", "đang giữ", "không khớp")]
    bt_row = conn.execute("SELECT avg_r FROM backtest_stats WHERE plan='Tất cả'").fetchone()
    summary = dict(
        n=len(items), filled=len(filled), pending=sum(x["status"] == "chờ khớp" for x in items),
        fill_rate=round(100 * len(filled) / len(decided)) if decided else None,
        closed=len(closed), avg_r=round(sum(x["R"] for x in closed) / len(closed), 2) if closed else None,
        win=round(100 * sum(x["R"] > 0 for x in closed) / len(closed)) if closed else None,
        sum_r=round(sum(x["R"] for x in filled), 2) if filled else None,
        backtest_avg_r=bt_row[0] if bt_row else None,
        first=items[0]["date"] if items else None, last=items[-1]["date"] if items else None)
    return dict(items=items[::-1], summary=summary)
