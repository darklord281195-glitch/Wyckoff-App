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
from .core.foreign import sync_foreign, net_sum
from .core.proprietary import sync_prop
from .core.wyckoff import analyse, trim
from .core.market import traffic_light
from .core import signals as sig
from .universe import universe, watchlist, refresh_listing, listing, INDEX
from . import notify, charts, backup
from .core import risk as risk_mod
from .core import sectors as sectors_mod
from .core import fundamentals as fund
from .core import paper
from .core import mcdx
from .core import rank as rank_mod
from .core import data as data_mod
from . import health

LIGHT_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴", "?": "⚪"}


def setup_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = LOG_DIR / f"scan-{dt.date.today():%Y%m%d}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(f, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    return logging.getLogger("scan")


def _upto(R, at):
    """Nến tới phiên `at` rồi cắt cửa sổ phân tích tính từ ngày đó (at=None: như phiên mới nhất)."""
    if not at:
        return trim(R)
    return trim([r for r in R if r["d"] <= at], today=dt.date.fromisoformat(at))


def run(groups=None, symbols=None, dry_run=False, photos=True, refresh=True, log=None, at=None):
    """at='YYYY-MM-DD': tạo lại kết quả của phiên cũ từ dữ liệu đã có, không tải mới, không gửi Telegram."""
    log = log or logging.getLogger("scan")
    conn = connect()
    if at:
        refresh, dry_run, photos = False, True, False
    if refresh:
        data_mod.FALLBACK_USED.clear()            # mã phải lấy giá từ nguồn dự phòng trong lần quét này
    IDX = _upto(get_ohlcv(conn, INDEX, 4000 if at else 600, refresh=refresh), at)
    if not IDX or (at and IDX[-1]["d"] != at):
        raise ValueError(f"Phiên {at} không có nến VNINDEX (không phải ngày giao dịch hoặc chưa có dữ liệu)")
    scan_date = IDX[-1]["d"]
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).date().isoformat()
    if refresh and not dry_run and scan_date < today:
        # nghỉ lễ / cuối tuần: VNINDEX không có nến hôm nay -> không quét, không gửi Telegram
        log.info("Không có phiên %s (VNINDEX mới nhất %s, nghỉ lễ?): bỏ qua lần quét", today, scan_date)
        return dict(date=scan_date, signals=[], n=0, errors=[], message="", skipped=True)
    idx_res = analyse(IDX)

    wl = set(watchlist(conn))
    if refresh and not symbols and not groups:
        try:
            log.info("Danh sách HOSE+HNX: %d mã", refresh_listing(conn))
        except Exception as e:
            log.warning("Không cập nhật được danh sách mã (%s), dùng danh sách cũ", e)
    lst = listing(conn)
    held = {}                                     # lệnh đang giữ theo mã
    if at:     # phiên cũ: lệnh đã mua tới phiên đó và chưa bán hết trước phiên đó
        held_q = ("SELECT * FROM positions WHERE entry_d<=? AND (exit_d IS NULL OR exit_d>?)", (scan_date, scan_date))
    else:
        held_q = ("SELECT * FROM positions WHERE status='open'", ())
    for p in conn.execute(*held_q):
        held.setdefault(p["sym"], []).append(dict(p, targets=json.loads(p["targets"] or "[]")))
    syms = symbols or universe(conn, groups)
    results, all_sigs, errors = {}, [], []
    if refresh:
        t0 = time.time()
        errors += sync_many(conn, syms, 500, workers=6)
        log.info("Tải dữ liệu %d mã trong %.0f giây (lỗi %d)", len(syms), time.time() - t0, len(errors))
        # khối ngoại: chỉ mã có GT TB20 ≥ 1 tỷ (mã kém thanh khoản hầu như không có giao dịch nước ngoài)
        t0, fx_syms = time.time(), []
        for s in syms:
            R0 = get_ohlcv(conn, s, 60, refresh=False)
            if len(R0) >= 20 and sum(r["v"] for r in R0[-20:]) / 20 * R0[-1]["c"] >= 1:
                fx_syms.append(s)
        try:
            fx_err = sync_foreign(conn, fx_syms, scan_date)
            log.info("Khối ngoại %d mã trong %.0f giây (lỗi %d)", len(fx_syms), time.time() - t0, len(fx_err))
        except Exception as e:                  # khối ngoại lỗi không được làm hỏng lần quét
            log.warning("Không tải được khối ngoại: %s", e)
        try:                                    # tự doanh (CafeF) cho mã đủ thanh khoản: điểm Dòng tiền của Top 10
            t0 = time.time()
            prop_syms = [s for s in fx_syms if (lambda R0: sum(r["v"] for r in R0[-20:]) / 20 * R0[-1]["c"] >= MIN_LIQ_BIL)(
                get_ohlcv(conn, s, 60, refresh=False))]
            p_err = sync_prop(conn, prop_syms, scan_date)
            log.info("Tự doanh %d mã trong %.0f giây (lỗi %d)", len(prop_syms), time.time() - t0, len(p_err))
        except Exception as e:
            log.warning("Không tải được tự doanh: %s", e)
        try:                                    # BCTC quý: chỉ mã đủ thanh khoản, tải lại mỗi tuần
            t0 = time.time()
            liquid = [s for s in fx_syms if (lambda R0: sum(r["v"] for r in R0[-20:]) / 20 * R0[-1]["c"] >= MIN_LIQ_BIL)(
                get_ohlcv(conn, s, 60, refresh=False))]
            f_err = fund.sync(conn, liquid)
            log.info("BCTC %d mã (tải lại mã cũ hơn %d ngày) trong %.0f giây (lỗi %d)",
                     len(liquid), fund.REFRESH_DAYS, time.time() - t0, len(f_err))
        except Exception as e:
            log.warning("Không tải được BCTC: %s", e)
    skipped = 0
    for i, s in enumerate(syms, 1):
        try:
            R = _upto(get_ohlcv(conn, s, 4000 if at else 500, refresh=False), at)
            if len(R) < 120 or R[-1]["d"] != scan_date:
                skipped += 1; continue
            r = analyse(R, IDX, (lst.get(s) or {}).get("floor") or "UPCOM")
            if not r: continue
            r["fx10"] = net_sum(conn, s, scan_date)          # khối ngoại mua ròng 10 phiên (tỷ đồng)
            r["mcdx"] = mcdx.last([x["c"] for x in R])        # MCDX Plus: % banker / hot money / nhỏ lẻ
            results[s] = r
            prev_row = conn.execute("SELECT data FROM scan_results WHERE sym=? AND date<? ORDER BY date DESC LIMIT 1",
                                    (s, scan_date)).fetchone()
            prev = json.loads(prev_row[0]) if prev_row else None
            conn.execute("INSERT OR REPLACE INTO scan_results(date,sym,stage,data) VALUES (?,?,?,?)",
                         (scan_date, s, r["tag"], json.dumps(r, ensure_ascii=False)))
            conn.execute("DELETE FROM signals WHERE date=? AND sym=?", (scan_date, s))   # quét lại cùng ngày
            xs = sig.build(s, r, prev, s in wl)
            if s in held:      # R chỉ có ~420 ngày, lệnh có thể mua sớm hơn -> lấy đủ lịch sử
                xs += sig.position_alerts(s, held[s], [b for b in get_ohlcv(conn, s, 4000, refresh=False) if b["d"] <= scan_date], r.get("rs20"))
            for x in xs:
                had = conn.execute("SELECT 1 FROM signals WHERE sym=? AND kind=? AND date<? ORDER BY date DESC LIMIT 1",
                                   (s, x["kind"], scan_date)).fetchone()
                last_d = conn.execute("SELECT max(date) FROM signals WHERE date<?", (scan_date,)).fetchone()[0]
                had_yday = had and conn.execute("SELECT 1 FROM signals WHERE sym=? AND kind=? AND date=?",
                                                (s, x["kind"], last_d)).fetchone()
                x["is_new"] = 0 if had_yday else 1
                conn.execute("INSERT OR REPLACE INTO signals(date,sym,kind,is_new,text,replay) VALUES (?,?,?,?,?,?)",
                             (scan_date, s, x["kind"], x["is_new"], x["text"], 1 if at else 0))
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
    if not symbols and not groups:          # quét ít mã thì mỗi ngành không đủ mẫu
        sectors_mod.save(conn, scan_date, sectors_mod.sector_stats(results, lst, MIN_LIQ_BIL))
    # backtest: các loại tín hiệu mua có R trung bình âm theo màu đèn -> không báo mua, chỉ giữ cảnh báo và danh mục
    kinds = sig.HIDE.get(market["light"], ())
    hidden = sorted({x["sym"] for x in all_sigs if x["kind"] in kinds})
    if hidden:
        conn.execute(f"DELETE FROM signals WHERE date=? AND sym IN ({','.join('?' * len(hidden))}) "
                     f"AND kind IN ({','.join('?' * len(kinds))})", (scan_date, *hidden, *kinds))
        all_sigs = [x for x in all_sigs if x["kind"] not in kinds]
    conn.commit()
    log.info("Phân tích %d mã, bỏ qua %d mã (dưới 120 phiên hoặc không giao dịch phiên %s)",
             len(results), skipped, scan_date)
    top10 = None
    if not symbols and not groups:          # Top 10 tiềm năng: lưu snapshot phiên (kể cả phiên cũ), so với phiên trước
        try:
            top10 = rank_mod.daily_top(conn, scan_date, market["light"])
        except Exception as e:
            log.warning("Không tính được Top 10 tiềm năng: %s", e)

    msg = format_message(scan_date, market, all_sigs, results, errors, hidden, kinds, top10)
    fb = sorted(data_mod.FALLBACK_USED) if refresh else []
    if fb:
        log.warning("VNDirect lỗi: %d mã lấy giá từ nguồn dự phòng DNSE: %s", len(fb), ", ".join(fb))
        msg += (f"\n\n⚠️ VNDirect lỗi: {len(fb)} mã lấy giá từ nguồn dự phòng (DNSE): {', '.join(fb[:10])}"
                + ("…" if len(fb) > 10 else ""))
    if not at:                    # sổ lệnh thử nghiệm (app tự mua 14h10): luật bán làm gì hôm nay
        try:
            ev = paper.events_on(conn, scan_date)
            if ev:
                msg += "\n\n📒 Sổ thử nghiệm (tự bán theo luật):\n" + "\n".join("  " + x for x in ev)
        except Exception as e:
            log.warning("Không tính được sổ thử nghiệm: %s", e)
    if not at:                    # cảnh báo rủi ro danh mục (vốn, ngưỡng ở trang Danh mục)
        try:
            pr = risk_mod.portfolio_risk(risk_mod.open_positions(conn), risk_mod.get_settings(conn),
                                         {s: (v.get("icb_name") or "") for s, v in lst.items()}, market["light"])
            if pr["warnings"]:
                msg += "\n\n⚖️ Rủi ro danh mục:\n" + "\n".join("  " + w for w in pr["warnings"])
        except Exception as e:
            log.warning("Không tính được rủi ro danh mục: %s", e)
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


def format_top(top: dict, light: str | None = None) -> list[str]:
    """Đoạn Top 10 tiềm năng trong tin cuối ngày (top = rank.daily_top)."""
    rows = top.get("rows") or []
    if not rows:
        return []
    out = [f"\n🏆 Top {len(rows)} tiềm năng (điểm %: Wyckoff · KT&CB · Dòng tiền)"
           + (" (đèn đỏ: chỉ để theo dõi)" if light == "red" else "") + ":",
           "  " + " · ".join(f"{x['sym']} {x['total']}" + (" 🆕" if x.get("new") else "") for x in rows)]
    if top.get("dropped"):
        out.append("  Rời top: " + ", ".join(x["sym"] for x in top["dropped"]))
    out.append(f"  {WEB_URL}/top")
    return out


def format_message(scan_date, market, sigs, results, errors, hidden=(), kinds=(), top=None) -> str:
    c = market.get("c")
    head = (f"📊 Wyckoff {fmt.date_full(scan_date)} · VNINDEX {fmt.num(c, 2)} ({fmt.pct(market.get('chg') or 0, 2)}) "
            f"{LIGHT_ICON[market['light']]}\n{market['text']}") if c else "📊 Wyckoff"
    lines = [head]
    if hidden:
        what = "tín hiệu mua" if set(kinds) == set(sig.BUY) else "tín hiệu " + "/".join(kinds)
        lines.append(f"\n{LIGHT_ICON[market['light']]} Đèn {'đỏ' if market['light'] == 'red' else 'vàng'}: "
                     f"tạm ẩn {what} của {', '.join(hidden)} (backtest: kỳ vọng âm ở màu đèn này). "
                     "Xem vùng vào trên web khi đèn chuyển xanh.")
    groups = {}
    for x in sorted(sigs, key=lambda x: (x["prio"], -(x["rs20"] or -99))):
        groups.setdefault(x["kind"], []).append(x)
    titles = {"Cắt lỗ": "Danh mục – cần bán (thủng cắt lỗ)", "Hết thời gian": "Danh mục – hết thời gian chờ",
              "Chốt lời": "Danh mục – chốt lời", "Dời cắt lỗ": "Danh mục – dời cắt lỗ",
              "LPS": "Đáng chú ý – đang ở LPS", "SOS mới": "SOS mới (chờ LPS/Backup)", "Spring": "Spring/ST hôm nay",
              "Tiềm năng sớm": "Tiềm năng sớm (sắp phá trần)", "D sớm": "Mới vào Pha D sớm",
              "Chốt lời?": "Cân nhắc chốt lời", "Rời Pha D": "Cảnh báo", "Gãy hỗ trợ": "Cảnh báo",
              "UTAD": "Dấu hiệu phân phối (mã đang giữ/theo dõi)"}
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
    if top:
        lines += format_top(top, market.get("light"))
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


RETRIES, RETRY_WAIT = 2, 600      # chưa có nến hôm nay: thử lại sau 10 và 20 phút (trong giới hạn 30 phút của task)


def run_with_retry(do, log):
    """Chưa có phiên hôm nay có thể là nghỉ lễ hoặc VNDirect cập nhật trễ: thử lại, hết lượt thì báo Telegram."""
    for i in range(RETRIES + 1):
        r = do()
        if not r.get("skipped"):
            return r
        if i < RETRIES:
            log.info("Chưa có nến VNINDEX hôm nay, thử lại sau %d phút (%d/%d)", RETRY_WAIT // 60, i + 1, RETRIES)
            time.sleep(RETRY_WAIT)
    if notify.enabled():
        notify.send_text(f"⚠️ Wyckoff: chưa có dữ liệu phiên hôm nay (VNINDEX mới nhất {fmt.day(r['date'])}), "
                         f"đã thử lại {RETRIES} lần. Nghỉ lễ thì bỏ qua; nếu hôm nay có giao dịch, "
                         f"mở web bấm Quét lại sau ít phút: {WEB_URL}")
    return r


def job_detail(r: dict) -> dict:
    """Chi tiết một lần quét cho bảng job_runs (trang Hệ thống, watchdog)."""
    return dict(date=r["date"], n=r["n"], signals=len(r["signals"]), errors=r["errors"][:100],
                n_errors=len(r["errors"]), fallback=sorted(data_mod.FALLBACK_USED))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups"); ap.add_argument("--symbols")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--no-photo", action="store_true")
    ap.add_argument("--offline", action="store_true", help="không tải dữ liệu mới, dùng cache")
    ap.add_argument("--from", dest="since", metavar="YYYY-MM-DD",
                    help="tạo lại kết quả các phiên cũ từ ngày này (không tải dữ liệu, không gửi Telegram)")
    ap.add_argument("--to", metavar="YYYY-MM-DD", help="cùng --from: tới ngày này (mặc định = --from)")
    a = ap.parse_args()
    log = setup_log()
    if a.since:
        conn = connect()
        days = [r[0] for r in conn.execute("SELECT d FROM ohlcv WHERE sym=? AND d>=? AND d<=? ORDER BY d",
                                           (INDEX, a.since, a.to or a.since))]
        if not days:
            log.error("Không có phiên giao dịch nào trong khoảng %s–%s", a.since, a.to or a.since); sys.exit(1)
        logging.getLogger().handlers[-1].setLevel(logging.WARNING)   # bớt in tin nhắn từng phiên ra màn hình
        for d in days:                                               # tăng dần: cờ "mới" dựa vào phiên trước
            r = run(groups=a.groups.split(",") if a.groups else None,
                    symbols=[s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None, log=log, at=d)
            print(f"{d}: {r['n']} mã · {len(r['signals'])} tín hiệu · lỗi {len(r['errors'])}", flush=True)
        return
    started = health.now_vn().isoformat(timespec="seconds")
    try:
        r = run_with_retry(lambda: run(groups=a.groups.split(",") if a.groups else None,
                                       symbols=[s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None,
                                       dry_run=a.dry_run, photos=not a.no_photo, refresh=not a.offline, log=log), log)
    except Exception as e:                       # ghi lại để trang Hệ thống / watchdog thấy, rồi vẫn báo lỗi như cũ
        if not a.dry_run:
            health.record(connect(), "scan", started, "error", dict(error=str(e)[:500]))
        raise
    if not a.dry_run and not a.symbols and not a.groups:        # chỉ lần quét đầy đủ mới tính là "đã quét phiên"
        health.record(connect(), "scan", started, "skipped" if r.get("skipped") else "ok", job_detail(r))
    started = health.now_vn().isoformat(timespec="seconds")
    try:
        path = backup.backup()
        log.info("Sao lưu danh mục: %s", path)
        health.record(connect(), "backup", started, "ok", dict(path=str(path)))
    except Exception as e:                       # sao lưu lỗi không được làm hỏng lần quét
        log.warning("Không sao lưu được danh mục: %s", e)
        health.record(connect(), "backup", started, "error", dict(error=str(e)[:300]))


if __name__ == "__main__":
    main()
