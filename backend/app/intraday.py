"""Việc TRONG PHIÊN, dùng nến ngày đang chạy của VNDirect (không ghi vào DB):
1. Cảnh báo giá: mã đang giữ chạm cắt lỗ / mục tiêu, mã watchlist vào vùng mua (mốc từ lần quét cuối ngày gần nhất).
   Luật bán vẫn theo giá ĐÓNG CỬA, tin nhắn chỉ là "chú ý".
2. Tự mua thử nghiệm 14h10–14h29 (auto_buy): quét mọi mã đủ thanh khoản, phân tích lại với nến hôm nay; mã đạt
   đúng "Kịch bản mua đẹp" (good_setup) thì ghi vào sổ lệnh thử nghiệm (core/paper.py) và báo Telegram. Sổ này tự
   bán theo luật để đo điểm mua nào đúng / sai, không phải lệnh thật và không đụng Danh mục.
Mỗi cảnh báo / mỗi mã mua tối đa 1 lần/ngày.

  .venv\\Scripts\\python -m app.intraday --dry-run          # kiểm tra 1 lần, chỉ in
  .venv\\Scripts\\python -m app.intraday --dry-run --auto   # thử tự mua thử nghiệm ngay (không ghi, không gửi)
  .venv\\Scripts\\python -m app.intraday --loop             # 9:15–14:45 thứ 2–6, mỗi 5 phút (Task Scheduler gọi lúc 9:10)
"""
import argparse, json, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor

from .config import MIN_LIQ_BIL
from .db import connect
from .fmt import price as _p, num, pct
from .core.data import fetch_remote, get_ohlcv
from .core.positions import simulate
from .core.wyckoff import analyse, trim
from .core.market import traffic_light
from .core.plan import BUY_KINDS
from .core import paper
from .universe import INDEX, listing
from . import notify

VN = dt.timezone(dt.timedelta(hours=7))
EVERY = 300                                       # giây giữa hai lần kiểm tra
SESSIONS = ((dt.time(9, 15), dt.time(11, 30)), (dt.time(13, 0), dt.time(14, 45)))
AUTO = (dt.time(14, 10), dt.time(14, 29))         # tự mua thử nghiệm: nến ngày gần xong, kịp đặt LO trước ATC
VOL_SO_FAR = 0.85                                 # tới ~14h20 thường đã khớp 85–90% KL ngày
TURN = ("LPS", "LPS mới (vượt trần hỏng)", "LPS sâu (vượt trần hỏng)", "Backup")   # cần phiên quay đầu (đóng cửa tăng)
LIGHT_VN = {"green": "xanh", "yellow": "vàng", "red": "đỏ"}


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


def good_setup(plan: dict | None, R: list[dict], res: float | None = None) -> tuple[bool, str]:
    """Mã có đạt "Kịch bản mua đẹp" ngay lúc này không (luật của skill wyckoff). R[-1] = nến hôm nay đang chạy.
    Trả (đạt?, lý do không đạt / mô tả ngắn khi đạt)."""
    p = plan or {}
    if p.get("kind") not in BUY_KINDS or not p.get("entry_lo"):
        return False, f"kế hoạch {p.get('kind') or '–'} không có điểm mua"
    b, y = R[-1], R[-2]
    v20 = sum(x["v"] for x in R[-21:-1]) / 20
    if not p["entry_lo"] <= b["c"] <= p["entry_hi"]:
        return False, f"giá {_p(b['c'])} ngoài vùng mua {_p(p['entry_lo'])}–{_p(p['entry_hi'])}"
    if (p.get("rr") or 0) < 2:
        return False, f"lời/lỗ {num(p.get('rr') or 0, 1)} < 2"
    rng = b["h"] - b["l"]
    if rng > 0 and (b["c"] - b["l"]) / rng < 0.5:
        return False, "giá ở nửa dưới biên độ phiên"
    if p["kind"] in TURN and b["c"] <= y["c"]:
        return False, "chưa phải phiên quay đầu (giá chưa tăng so với hôm qua)"
    vx = b["v"] / v20 if v20 else 9
    if p["kind"] == "Phá trần (SOS)":
        if res and b["c"] <= res:
            return False, f"chưa vượt trần {_p(res)}"
        if vx < VOL_SO_FAR * 1.5:
            return False, f"KL x{num(vx, 1)} chưa đủ lớn cho phiên phá trần"
    elif vx >= VOL_SO_FAR:
        return False, f"KL x{num(vx, 1)} đã cao (cần dưới x{num(VOL_SO_FAR, 2)} lúc này)"
    if p.get("selloff"):          # sau phiên bán mạnh: cần ≥ 2 phiên lùi KL < TB20, tính cả hôm nay
        after = [x for x in R if x["d"] > p["selloff"]]
        if len(after) < 2 or any(x["v"] >= v20 for x in after):
            return False, f"vừa bán mạnh {p['selloff'][8:]}/{p['selloff'][5:7]}, chưa đủ 2 phiên lùi KL thấp"
    return True, f"{p['kind']} · KL x{num(vx, 1)} · lời/lỗ {num(p['rr'], 1)}"


def _today_bars(syms, today, fetch, workers=6):
    """{mã: nến hôm nay} tải song song; mã lỗi mạng / chưa có nến hôm nay thì bỏ qua."""
    def job(s):
        try:
            bars = fetch(s, 7)
        except Exception:
            return s, None
        return s, bars[-1] if bars and bars[-1]["d"] == today else None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return {s: b for s, b in ex.map(job, syms) if b}


def _with_today(conn, sym, bar, days=500):
    return [x for x in get_ohlcv(conn, sym, days, refresh=False) if x["d"] < bar["d"]] + [bar]


def auto_buy(conn, dry_run=False, log=print, fetch=fetch_remote, now=None):
    """Quét mọi mã đủ thanh khoản với nến hôm nay; mã đạt good_setup thì ghi vào sổ lệnh thử nghiệm (core/paper)
    ở giá lúc kiểm tra và báo. Không đụng Danh mục thật. Trả các dòng đã báo."""
    now = now or dt.datetime.now(VN)
    today = now.date().isoformat()
    last = conn.execute("SELECT max(date) FROM scan_results WHERE date<?", (today,)).fetchone()[0]
    if not last:
        return []
    held = paper.open_syms(conn)              # mã đang có lệnh thử nghiệm chưa bán hết: không mua chồng
    done = {r[0] for r in conn.execute("SELECT sym FROM paper_trades WHERE d=?", (today,))}
    idx_prev, cands = None, []
    for sym, data in conn.execute("SELECT sym, data FROM scan_results WHERE date=?", (last,)).fetchall():
        d = json.loads(data)
        if sym == INDEX:
            idx_prev = d
        elif d and (d.get("liq") or 0) >= MIN_LIQ_BIL and sym not in held and sym not in done:
            cands.append(sym)
    bars = _today_bars(cands + [INDEX], today, fetch)
    if INDEX not in bars:
        log("Chưa có nến VNINDEX hôm nay: bỏ qua tự mua thử nghiệm")
        return []
    IDX = trim(_with_today(conn, INDEX, bars[INDEX], 600))
    light = traffic_light(analyse(IDX), (idx_prev or {}).get("breadth"))["light"]
    lst = listing(conn)
    hits = []
    for s in cands:
        if s not in bars:
            continue
        R = _with_today(conn, s, bars[s])
        if len(R) < 120:
            continue
        try:
            a = analyse(trim(R), IDX, (lst.get(s) or {}).get("floor") or "UPCOM")
        except Exception as e:                    # một mã lỗi không được chặn cả lượt quét
            log(f"{s}: {e}")
            continue
        p = (a or {}).get("plan")
        ok, why = good_setup(p, R, ((a or {}).get("range") or {}).get("res"))
        if ok:
            hits.append((s, bars[s], p, why))
    if not hits:
        return []
    at = f"{now:%H:%M}"
    rows, lines = [], []
    for sym, b, p, why in sorted(hits, key=lambda h: -(h[2].get("rr") or 0)):
        rng = b["h"] - b["l"]
        v20 = sum(x["v"] for x in _with_today(conn, sym, b)[-21:-1]) / 20
        rows.append(dict(d=today, at=at, sym=sym, kind=p["kind"], entry_px=b["c"], stop=p["stop"],
                         targets=[t["price"] for t in p.get("targets", [])], light=light, rr=p["rr"],
                         vx=round(b["v"] / v20, 2) if v20 else None,
                         close_pos=round((b["c"] - b["l"]) / rng, 2) if rng > 0 else 1.0, why=why, plan=p))
        lines.append(f"📒 {sym} {_p(b['c'])} · {why} · vùng {_p(p['entry_lo'])}–{_p(p['entry_hi'])} · "
                     f"cắt lỗ {_p(p['stop'])} ({pct((p['stop'] / b['c'] - 1) * 100)})"
                     + (f" · T1 {_p(p['targets'][0]['price'])}" if p.get("targets") else "")
                     + f" · đèn {LIGHT_VN.get(light, '?')}")
    if not dry_run:
        paper.record(conn, rows)
        conn.executemany("INSERT OR IGNORE INTO intraday_alerts(date, sym, kind, text, at) VALUES (?,?,?,?,?)",
                         [(today, r["sym"], "buy", t, at) for r, t in zip(rows, lines)])
        conn.commit()
    msg = f"📒 Sổ thử nghiệm {at} – app tự mua (không phải lệnh thật), sẽ tự bán theo luật:\n" + "\n".join(lines)
    log(msg)
    if not dry_run and notify.enabled():
        notify.send_text(msg)
    return lines


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
            icon = {"stop": "⛔", "target": "💰", "zone": "🎯"}[kind]
            line = f"{icon} {s} {_p(bar['c'])} · {text}"
            if dry_run or conn.execute("INSERT OR IGNORE INTO intraday_alerts(date, sym, kind, text, at) VALUES (?,?,?,?,?)",
                                       (today, s, kind, line, f"{dt.datetime.now(VN):%H:%M}")).rowcount:
                lines.append(line)
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


def in_auto(now):
    return now.weekday() < 5 and AUTO[0] <= now.time() <= AUTO[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--auto", action="store_true", help="chạy tự mua thử nghiệm ngay, không chờ 14h10")
    ap.add_argument("--only-auto", action="store_true",
                    help="chỉ tự mua thử nghiệm 14h10–14h29, không cảnh báo giá (Task Scheduler gọi lúc 14:05)")
    a = ap.parse_args()
    conn = connect()
    if not a.loop:
        if not a.only_auto:
            run_once(conn, a.dry_run) or print("Không có cảnh báo.")
        if a.auto or in_auto(dt.datetime.now(VN)):
            auto_buy(conn, a.dry_run) or print("Không có mã đạt kịch bản mua đẹp.")
        return
    end = AUTO[1] if a.only_auto else SESSIONS[-1][1]
    while dt.datetime.now(VN).time() < end:
        now = dt.datetime.now(VN)
        if in_session(now):
            jobs = () if a.only_auto else (run_once,)
            for job in jobs + ((auto_buy,) if in_auto(now) else ()):
                try:
                    job(conn, a.dry_run)
                except Exception as e:            # mạng lỗi một lần không được làm dừng cả ngày
                    print("Lỗi:", e)
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
