"""Cảnh báo giá TRONG PHIÊN (không phải quét Wyckoff): mã đang giữ chạm cắt lỗ / mục tiêu, mã watchlist vào vùng mua.
Mốc lấy từ lần quét cuối ngày gần nhất; giá hiện tại = nến ngày đang chạy của VNDirect (không ghi vào DB).
Luật bán vẫn theo giá ĐÓNG CỬA, tin nhắn chỉ là "chú ý". Mỗi cảnh báo gửi tối đa 1 lần/ngày.

  .venv\\Scripts\\python -m app.intraday --dry-run   # kiểm tra 1 lần, chỉ in
  .venv\\Scripts\\python -m app.intraday --loop      # 9:15–14:45 thứ 2–6, mỗi 5 phút (Task Scheduler gọi lúc 9:10)
"""
import argparse, json, time, datetime as dt

from .db import connect
from .fmt import price as _p
from .core.data import fetch_remote, get_ohlcv
from .core.positions import simulate
from . import notify

VN = dt.timezone(dt.timedelta(hours=7))
EVERY = 300                                       # giây giữa hai lần kiểm tra
SESSIONS = ((dt.time(9, 15), dt.time(11, 30)), (dt.time(13, 0), dt.time(14, 45)))


def check(bar, stop=None, target=None, plan=None):
    """[(kind, text)] cho một nến đang chạy. stop/target: lệnh đang giữ; plan: kế hoạch mua (mã watchlist)."""
    out = []
    if stop and bar["l"] <= stop:
        out.append(("stop", f"chạm cắt lỗ {_p(stop)} (thấp nhất {_p(bar['l'])})"))
    if target and bar["h"] >= target:
        out.append(("target", f"chạm mục tiêu {_p(target)} (cao nhất {_p(bar['h'])})"))
    lo, hi = (plan or {}).get("entry_lo"), (plan or {}).get("entry_hi")
    if lo and hi and bar["l"] <= hi and bar["h"] >= lo:
        out.append(("zone", f"vào vùng mua {_p(lo)}–{_p(hi)} ({plan.get('kind')})"))
    return out


def run_once(conn, dry_run=False, log=print):
    today = dt.datetime.now(VN).date().isoformat()
    held = {}
    for p in conn.execute("SELECT * FROM positions WHERE status='open'"):
        held.setdefault(p["sym"], []).append(dict(p, targets=json.loads(p["targets"] or "[]")))
    syms = sorted(set(held) | {r[0] for r in conn.execute("SELECT sym FROM watchlist")})
    lines = []
    for s in syms:
        try:
            bars = fetch_remote(s, 7)
        except Exception as e:
            log(f"{s}: {e}"); continue
        if not bars or bars[-1]["d"] != today:
            continue                              # chưa có nến hôm nay (ngoài giờ / ngày nghỉ)
        bar, alerts = bars[-1], []
        if s in held:
            hist = get_ohlcv(conn, s, 4000, refresh=False)
            for p in held[s]:
                past = [b for b in hist if p["entry_d"] <= b["d"] < today]
                if not past:                      # mua ngay hôm nay: chưa có gì để tính lại, dùng mốc gốc
                    alerts += check(bar, stop=p["stop"], target=(p["targets"] or [None])[0]); continue
                st = simulate(p["entry_px"], p["stop"], p["targets"], past)
                if st["open"]:
                    alerts += check(bar, stop=st["stop"], target=st["next"])
        else:
            row = conn.execute("SELECT data FROM scan_results WHERE sym=? ORDER BY date DESC LIMIT 1", (s,)).fetchone()
            plan = row and json.loads(row[0]).get("plan")
            if plan and plan.get("entry_lo"):            # "Không vào" / "Chờ (Pha B)" chưa có vùng mua
                alerts += check(bar, plan=plan)
        for kind, text in dict(alerts).items():    # nhiều lệnh cùng mã: mỗi loại 1 dòng
            if dry_run or conn.execute("INSERT OR IGNORE INTO intraday_alerts(date, sym, kind) VALUES (?,?,?)",
                                       (today, s, kind)).rowcount:
                icon = {"stop": "⛔", "target": "💰", "zone": "🎯"}[kind]
                lines.append(f"{icon} {s} {_p(bar['c'])} · {text}")
    conn.commit()
    if lines:
        msg = (f"⏰ Trong phiên {dt.datetime.now(VN):%H:%M} – chú ý, chưa phải lệnh:\n" + "\n".join(lines) +
               "\nLuật bán theo giá đóng cửa: chờ hết phiên rồi mới quyết định cắt lỗ.")
        log(msg)
        if not dry_run and notify.enabled():
            notify.send_text(msg)
    return lines


def in_session(now):
    return now.weekday() < 5 and any(a <= now.time() <= b for a, b in SESSIONS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    conn = connect()
    if not a.loop:
        run_once(conn, a.dry_run) or print("Không có cảnh báo.")
        return
    while dt.datetime.now(VN).time() < SESSIONS[-1][1]:
        if in_session(dt.datetime.now(VN)):
            try:
                run_once(conn, a.dry_run)
            except Exception as e:                # mạng lỗi một lần không được làm dừng cả ngày
                print("Lỗi:", e)
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
