"""Quét cuối ngày: cập nhật dữ liệu -> phân tích Wyckoff -> lưu DB -> sinh tín hiệu -> gửi Telegram.

Cách dùng (trong thư mục backend):
  .venv\\Scripts\\python -m app.scan                 # quét toàn bộ, gửi Telegram
  .venv\\Scripts\\python -m app.scan --dry-run       # không gửi Telegram, chỉ in
  .venv\\Scripts\\python -m app.scan --groups ck,bds --symbols TCH,DPG --no-photo --offline
"""
import argparse, json, logging, sys, time, datetime as dt

from .config import LOG_DIR, WEB_URL, MIN_LIQ_BIL
from . import fmt
from .db import connect
from .core.data import get_ohlcv, sync_many
from .core.wyckoff import analyse, trim
from .core.market import traffic_light
from .core import signals as sig
from .universe import universe, watchlist, refresh_listing, listing, INDEX
from . import notify, charts

LIGHT_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴", "?": "⚪"}


def setup_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = LOG_DIR / f"scan-{dt.date.today():%Y%m%d}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(f, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    return logging.getLogger("scan")


def run(groups=None, symbols=None, dry_run=False, photos=True, refresh=True, log=None):
    log = log or logging.getLogger("scan")
    conn = connect()
    IDX = trim(get_ohlcv(conn, INDEX, 600, refresh=refresh))
    idx_res = analyse(IDX)
    scan_date = IDX[-1]["d"]

    wl = set(watchlist(conn))
    if refresh and not symbols and not groups:
        try:
            log.info("Danh sách HOSE+HNX: %d mã", refresh_listing(conn))
        except Exception as e:
            log.warning("Không cập nhật được danh sách mã (%s), dùng danh sách cũ", e)
    lst = listing(conn)
    held = {}                                     # lệnh đang giữ theo mã
    for p in conn.execute("SELECT * FROM positions WHERE status='open'"):
        held.setdefault(p["sym"], []).append(dict(p, targets=json.loads(p["targets"] or "[]")))
    syms = symbols or universe(conn, groups)
    results, all_sigs, errors = {}, [], []
    if refresh:
        t0 = time.time()
        errors += sync_many(conn, syms, 500, workers=6)
        log.info("Tải dữ liệu %d mã trong %.0f giây (lỗi %d)", len(syms), time.time() - t0, len(errors))
    skipped = 0
    for i, s in enumerate(syms, 1):
        try:
            R = trim(get_ohlcv(conn, s, 500, refresh=False))
            if len(R) < 120 or R[-1]["d"] != scan_date:
                skipped += 1; continue
            r = analyse(R, IDX, (lst.get(s) or {}).get("floor") or "UPCOM")
            if not r: continue
            results[s] = r
            prev_row = conn.execute("SELECT data FROM scan_results WHERE sym=? AND date<? ORDER BY date DESC LIMIT 1",
                                    (s, scan_date)).fetchone()
            prev = json.loads(prev_row[0]) if prev_row else None
            conn.execute("INSERT OR REPLACE INTO scan_results(date,sym,stage,data) VALUES (?,?,?,?)",
                         (scan_date, s, r["tag"], json.dumps(r, ensure_ascii=False)))
            conn.execute("DELETE FROM signals WHERE date=? AND sym=?", (scan_date, s))   # quét lại cùng ngày
            xs = sig.build(s, r, prev, s in wl)
            if s in held:      # R chỉ có ~420 ngày, lệnh có thể mua sớm hơn -> lấy đủ lịch sử
                xs += sig.position_alerts(s, held[s], get_ohlcv(conn, s, 4000, refresh=False), r.get("rs20"))
            for x in xs:
                had = conn.execute("SELECT 1 FROM signals WHERE sym=? AND kind=? AND date<? ORDER BY date DESC LIMIT 1",
                                   (s, x["kind"], scan_date)).fetchone()
                last_d = conn.execute("SELECT max(date) FROM signals WHERE date<?", (scan_date,)).fetchone()[0]
                had_yday = had and conn.execute("SELECT 1 FROM signals WHERE sym=? AND kind=? AND date=?",
                                                (s, x["kind"], last_d)).fetchone()
                x["is_new"] = 0 if had_yday else 1
                conn.execute("INSERT OR REPLACE INTO signals(date,sym,kind,is_new,text) VALUES (?,?,?,?,?)",
                             (scan_date, s, x["kind"], x["is_new"], x["text"]))
                all_sigs.append(x)
            log.debug("[%d/%d] %s %s", i, len(syms), s, r["tag"])
        except Exception as e:
            errors.append(s); log.warning("%s: %s", s, e)
    # độ rộng = % mã thanh khoản trên MA50; quét ít mã (--symbols/--groups) thì không đủ mẫu, bỏ qua
    liq = [r for r in results.values() if r["liq"] >= MIN_LIQ_BIL]
    breadth = round(100 * sum(r["c"] > r["ma50"] for r in liq) / len(liq)) if len(liq) >= 30 else None
    if idx_res:
        idx_res["breadth"] = breadth
    market = traffic_light(idx_res, breadth)
    conn.execute("INSERT OR REPLACE INTO scan_results(date,sym,stage,data) VALUES (?,?,?,?)",
                 (scan_date, INDEX, idx_res and idx_res["tag"], json.dumps(idx_res, ensure_ascii=False)))
    # backtest 2019–2026: tín hiệu mua lúc đèn đỏ có R trung bình âm -> không báo mua, chỉ giữ cảnh báo và danh mục
    hidden = sorted({x["sym"] for x in all_sigs if x["kind"] in sig.BUY}) if market["light"] == "red" else []
    if hidden:
        conn.execute(f"DELETE FROM signals WHERE date=? AND sym IN ({','.join('?' * len(hidden))}) "
                     f"AND kind IN ({','.join('?' * len(sig.BUY))})", (scan_date, *hidden, *sig.BUY))
        all_sigs = [x for x in all_sigs if x["kind"] not in sig.BUY]
    conn.commit()
    log.info("Phân tích %d mã, bỏ qua %d mã (dưới 120 phiên hoặc không giao dịch phiên %s)",
             len(results), skipped, scan_date)

    msg = format_message(scan_date, market, all_sigs, results, errors, hidden)
    log.info("\n%s", msg)
    if dry_run or not notify.enabled():
        if not dry_run: log.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID trong .env - không gửi.")
        return dict(date=scan_date, signals=all_sigs, n=len(results), errors=errors, message=msg)
    if conn.execute("SELECT 1 FROM telegram_sent WHERE date=?", (scan_date,)).fetchone():
        log.info("Phiên %s đã gửi Telegram rồi (ngày lễ/quét lại) - không gửi trùng.", scan_date)
        return dict(date=scan_date, signals=all_sigs, n=len(results), errors=errors, message=msg)
    notify.send_text(msg)
    conn.execute("INSERT OR IGNORE INTO telegram_sent(date) VALUES (?)", (scan_date,)); conn.commit()
    if photos:
        top = sorted([x for x in all_sigs if x["prio"] < 5], key=lambda x: (x["prio"], -(x["rs20"] or -99)))
        seen = set()
        for x in top:
            if x["sym"] in seen or len(seen) >= 4: continue
            seen.add(x["sym"])
            R = trim(get_ohlcv(conn, x["sym"], 500, refresh=False))
            notify.send_photo(charts.render_png(x["sym"], R, results[x["sym"]]), caption=x["text"])
    return dict(date=scan_date, signals=all_sigs, n=len(results), errors=errors, message=msg)


def format_message(scan_date, market, sigs, results, errors, hidden=()) -> str:
    c = market.get("c")
    head = (f"📊 Wyckoff {fmt.date_full(scan_date)} · VNINDEX {fmt.num(c, 2)} ({fmt.pct(market.get('chg') or 0, 2)}) "
            f"{LIGHT_ICON[market['light']]}\n{market['text']}") if c else "📊 Wyckoff"
    lines = [head]
    if hidden:
        lines.append(f"\n🔴 Đèn đỏ: tạm ẩn tín hiệu mua của {', '.join(hidden)} "
                     "(backtest: mua lúc đèn đỏ có kỳ vọng âm). Xem vùng vào trên web khi đèn chuyển vàng/xanh.")
    groups = {}
    for x in sorted(sigs, key=lambda x: (x["prio"], -(x["rs20"] or -99))):
        groups.setdefault(x["kind"], []).append(x)
    titles = {"Cắt lỗ": "Danh mục – cần bán (thủng cắt lỗ)", "Hết thời gian": "Danh mục – hết thời gian chờ",
              "Chốt lời": "Danh mục – chốt lời", "Dời cắt lỗ": "Danh mục – dời cắt lỗ",
              "LPS": "Đáng chú ý – đang ở LPS", "SOS mới": "SOS mới (chờ LPS/Backup)", "Spring": "Spring/ST hôm nay",
              "Tiềm năng sớm": "Tiềm năng sớm (sắp phá trần)", "D sớm": "Mới vào Pha D sớm",
              "Chốt lời?": "Cân nhắc chốt lời", "Rời Pha D": "Cảnh báo", "Gãy hỗ trợ": "Cảnh báo"}
    for kind, xs in groups.items():
        lines.append(f"\n{sig.ICON[kind]} {titles[kind]}:")
        for x in xs:
            lines.append(f"  {'🆕 ' if x.get('is_new') else ''}{x['text']}" + (f" · RS20 {fmt.pct(x['rs20'])}" if x.get("rs20") is not None else ""))
    if not sigs:
        lines.append("\nHôm nay không có tín hiệu mới.")
    # danh sách Pha D còn lại (thanh khoản đủ, không bị đánh dấu giảm trước yếu) để theo dõi
    flagged = {x["sym"] for x in sigs}
    dlist = sorted([(s, r) for s, r in results.items() if r["stage"] == "D" and s not in flagged
                    and r["liq"] >= MIN_LIQ_BIL and not r.get("weak_drop")],
                   key=lambda t: -(t[1].get("rs20") or -99))
    if dlist:
        lines.append("\n📋 Pha D đang theo dõi:")
        lines.append("  " + " · ".join(f"{s} {r['tag']}" for s, r in dlist))
    nD = sum(1 for r in results.values() if r["stage"] == "D")
    nLiq = sum(1 for r in results.values() if r["liq"] >= MIN_LIQ_BIL)
    err = f" · lỗi {len(errors)} mã" + (f" ({', '.join(errors[:5])}{'…' if len(errors) > 5 else ''})" if errors else "") if errors else ""
    lines.append(f"\nĐã quét {len(results)} mã HOSE+HNX ({nLiq} mã GT ≥ {MIN_LIQ_BIL:g} tỷ) · {nD} mã ở Pha D{err}")
    lines.append(f"Xem chi tiết: {WEB_URL}")
    lines.append("Bộ lọc tự động – cần xem lại biểu đồ. Không phải khuyến nghị đầu tư.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups"); ap.add_argument("--symbols")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--no-photo", action="store_true")
    ap.add_argument("--offline", action="store_true", help="không tải dữ liệu mới, dùng cache")
    a = ap.parse_args()
    log = setup_log()
    run(groups=a.groups.split(",") if a.groups else None,
        symbols=[s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None,
        dry_run=a.dry_run, photos=not a.no_photo, refresh=not a.offline, log=log)


if __name__ == "__main__":
    main()
