"""Sức khỏe hệ thống: quét cuối ngày, dữ liệu giá, lỗi tải, nguồn dự phòng, khối ngoại, BCTC, sao lưu, Telegram,
task Windows, báo cáo tuần, tự mua thử nghiệm. Mỗi mục có mức ok / warn / error.

  .venv\\Scripts\\python -m app.health            # in trạng thái
  .venv\\Scripts\\python -m app.health --notify   # có mục lỗi thì gửi Telegram (tối đa 1 lần/ngày); task "Wyckoff Watchdog" 16:30
"""
import argparse, datetime as dt, json, os, subprocess, time

from .config import LOG_DIR, ROOT, MIN_LIQ_BIL
from .db import connect
from .universe import INDEX
from . import notify

VN = dt.timezone(dt.timedelta(hours=7))
SCAN_DONE = dt.time(16, 0)        # task quét 15:30, thử lại tối đa tới ~15:50: sau 16:00 phiên hôm nay phải có kết quả
AUTO_DONE = dt.time(14, 35)       # tự mua thử nghiệm chạy 14:10–14:29
TASKS = ("Wyckoff Scanner", "Wyckoff Intraday", "Wyckoff Weekly Review", "Wyckoff Watchdog")
TASK_OK = {0: "chạy xong", 267009: "đang chạy", 267011: "chưa chạy lần nào"}   # mã LastTaskResult của Task Scheduler
BACKUP_DIR = ROOT / "backups"
LEVELS = ("ok", "warn", "error")


def now_vn() -> dt.datetime:
    return dt.datetime.now(VN)


def record(conn, job: str, started: str, status: str, detail: dict | None = None):
    """Ghi một lần chạy tác vụ (scan / auto_buy / backup): status ok / skipped / error, detail JSON."""
    conn.execute("INSERT INTO job_runs(job, started, finished, status, detail) VALUES (?,?,?,?,?)",
                 (job, started, now_vn().isoformat(timespec="seconds"), status, json.dumps(detail or {}, ensure_ascii=False)))
    conn.commit()


def expected_session(now: dt.datetime) -> str:
    """Phiên gần nhất lẽ ra đã được quét: hôm nay nếu là ngày thường và đã qua SCAN_DONE, không thì ngày thường trước đó.
    App không có lịch nghỉ lễ: ngày lễ nhận ra qua lần quét bị bỏ qua (status skipped)."""
    d = now.date()
    if not (d.weekday() < 5 and now.time() >= SCAN_DONE):
        d -= dt.timedelta(days=1)
        while d.weekday() >= 5:
            d -= dt.timedelta(days=1)
    return d.isoformat()


def _day(d: str | None) -> str:
    return f"{d[8:10]}/{d[5:7]}" if d else "–"


def _last_job(conn, job: str) -> dict | None:
    r = conn.execute("SELECT * FROM job_runs WHERE job=? ORDER BY id DESC LIMIT 1", (job,)).fetchone()
    return dict(r, detail=json.loads(r["detail"] or "{}")) if r else None


_tasks_cache: dict = {}


def windows_tasks() -> dict | None:
    """{tên: dict(state, last, result, next)} các task "Wyckoff*" qua PowerShell (không phụ thuộc ngôn ngữ Windows);
    None nếu không phải Windows hoặc không đọc được. Lưu tạm 60 giây."""
    if os.name != "nt":
        return None
    if _tasks_cache and time.time() - _tasks_cache["t"] < 60:
        return _tasks_cache["v"]
    ps = ("Get-ScheduledTask -TaskName 'Wyckoff*' -ErrorAction SilentlyContinue | ForEach-Object { $i = $_ | Get-ScheduledTaskInfo; "
          "[pscustomobject]@{name=$_.TaskName; state=[string]$_.State; last=$i.LastRunTime.ToString('s'); result=$i.LastTaskResult; "
          "next=$(if ($i.NextRunTime) { $i.NextRunTime.ToString('s') } else { '' })} } | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                             text=True, encoding="utf-8", timeout=30).stdout.strip()
        rows = json.loads(out) if out else []
        v = {r["name"]: r for r in ([rows] if isinstance(rows, dict) else rows)}
    except Exception:
        v = None
    _tasks_cache.update(t=time.time(), v=v)
    return v


def status(conn, now: dt.datetime | None = None, tasks=windows_tasks) -> dict:
    """Trạng thái từng mục + mức chung (tệ nhất). tasks: hàm trả task Windows (test truyền hàm giả)."""
    now = now or now_vn()
    exp = expected_session(now)
    checks = []

    def add(key, label, level, detail):
        checks.append(dict(key=key, label=label, level=level, detail=detail))

    last_scan = conn.execute("SELECT max(date) FROM scan_results").fetchone()[0]
    job = _last_job(conn, "scan")
    skipped = bool(job and job["status"] == "skipped" and job["started"][:10] >= exp)
    # 1) quét cuối ngày
    if last_scan and last_scan >= exp:
        add("scan", "Quét cuối ngày", "ok", f"đã quét phiên {_day(last_scan)}"
            + (f", xong lúc {job['finished'][11:16]} ngày {_day(job['finished'][:10])}" if job and job["finished"] else ""))
    elif skipped:
        add("scan", "Quét cuối ngày", "warn", f"bỏ qua phiên {_day(exp)}: chưa có nến VNINDEX (nghỉ lễ?). "
                                               "Nếu hôm đó có giao dịch, mở Tổng quan bấm Quét lại")
    else:
        why = f"; lần chạy cuối ({job['started'][:16].replace('T', ' ')}) lỗi: {job['detail'].get('error', '')}" \
            if job and job["status"] == "error" else ""
        add("scan", "Quét cuối ngày", "error", f"chưa quét phiên {_day(exp)}"
            + (f" (lần gần nhất: phiên {_day(last_scan)})" if last_scan else " (chưa quét lần nào)") + why)
    # 2) dữ liệu giá: VNINDEX + mã thanh khoản bị cũ
    vni = conn.execute("SELECT max(d) FROM ohlcv WHERE sym=?", (INDEX,)).fetchone()[0]
    stale = []
    if vni and last_scan:
        liquid = [s for s, data in conn.execute("SELECT sym, data FROM scan_results WHERE date=?", (last_scan,))
                  if s != INDEX and ((json.loads(data) or {}).get("liq") or 0) >= MIN_LIQ_BIL]
        for i in range(0, len(liquid), 500):            # giới hạn số tham số của SQLite
            part = liquid[i:i + 500]
            stale += [s for s, d in conn.execute(f"SELECT sym, max(d) FROM ohlcv WHERE sym IN ({','.join('?' * len(part))}) "
                                                 "GROUP BY sym", part) if d < vni]
    if not vni:
        add("data", "Dữ liệu giá", "error", "chưa có dữ liệu VNINDEX")
    else:
        add("data", "Dữ liệu giá", "warn" if stale or (vni < exp and not skipped) else "ok",
            f"nến VNINDEX mới nhất {_day(vni)}" + (f"; {len(stale)} mã thanh khoản chưa có phiên này: {', '.join(sorted(stale)[:8])}"
                                                    + ("…" if len(stale) > 8 else "") if stale else ""))
    # 3) lỗi tải + 4) nguồn dự phòng của lần quét cuối
    if job and job["status"] in ("ok", "skipped"):
        errs, n_err = job["detail"].get("errors", []), job["detail"].get("n_errors", 0)
        add("errors", "Lỗi tải dữ liệu (lần quét cuối)", "ok" if not n_err else "warn" if n_err <= 20 else "error",
            "không có mã lỗi" if not n_err else f"{n_err} mã lỗi: {', '.join(errs[:8])}" + ("…" if n_err > 8 else ""))
        fb = job["detail"].get("fallback", [])
        add("fallback", "Nguồn dữ liệu", "warn" if fb else "ok",
            f"VNDirect lỗi, {len(fb)} mã lấy giá từ nguồn dự phòng DNSE: {', '.join(fb[:8])}" + ("…" if len(fb) > 8 else "")
            if fb else "VNDirect bình thường, không phải dùng nguồn dự phòng")
    # 5) khối ngoại, 6) BCTC
    fx = conn.execute("SELECT max(d) FROM foreign_trade").fetchone()[0]
    if vni:
        lag = conn.execute("SELECT count(*) FROM ohlcv WHERE sym=? AND d>?", (INDEX, fx or "0000")).fetchone()[0]
        add("foreign", "Khối ngoại", "ok" if fx and lag <= 2 else "warn",
            f"mới nhất {_day(fx)}" + (f", chậm {lag} phiên" if lag > 2 else "") if fx else "chưa có dữ liệu")
    fin = conn.execute("SELECT max(fetched) FROM fin_meta").fetchone()[0]
    age = (now.date() - dt.date.fromisoformat(fin[:10])).days if fin else None
    add("fundamentals", "BCTC (khối Cơ bản)", "ok" if age is not None and age <= 14 else "warn",
        f"tải lần cuối {_day(fin[:10])} ({age} ngày trước)" if fin else "chưa tải lần nào")
    # 7) sao lưu
    files = sorted(BACKUP_DIR.glob("portfolio-*.json"), key=lambda p: p.stat().st_mtime) if BACKUP_DIR.exists() else []
    if files:
        b_age = (time.time() - files[-1].stat().st_mtime) / 86400
        add("backup", "Sao lưu danh mục", "ok" if b_age <= 4 else "warn", f"{files[-1].name} ({b_age:.0f} ngày trước)")
    else:
        add("backup", "Sao lưu danh mục", "warn", "chưa có bản sao lưu nào (tạo sau mỗi lần quét)")
    # 8) Telegram
    add("telegram", "Telegram", "ok" if notify.enabled() else "warn",
        "đã cấu hình" if notify.enabled() else "chưa cấu hình TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID: không nhận được tin")
    # 9) task Windows, 10) báo cáo tuần, 11) tự mua thử nghiệm
    t = tasks()
    if t is not None:
        if not t:
            add("tasks", "Task tự động (Windows)", "warn", "máy này chưa đăng ký task nào (scripts\\register-task.ps1). "
                                                         "Bỏ qua nếu việc quét chạy ở máy khác")
        for name in TASKS if t else ():
            x = t.get(name)
            if not x:
                add("task:" + name, name, "warn", "chưa đăng ký (chạy lại scripts\\register-task.ps1)")
                continue
            code = x.get("result")
            ok = code in TASK_OK
            add("task:" + name, name, "ok" if code in (0, 267009) else "warn" if ok else "error",
                f"{'tắt' if x.get('state') == 'Disabled' else TASK_OK.get(code, f'lỗi mã 0x{(code or 0) & 0xFFFFFFFF:08X}')}"
                + (f" · lần cuối {x['last'][:16].replace('T', ' ')}" if code != 267011 else "")
                + (f" · lần tới {x['next'][:16].replace('T', ' ')}" if x.get("next") else ""))
        if t and "Wyckoff Weekly Review" in t:
            reviews = sorted(LOG_DIR.glob("review-*.md"), key=lambda p: p.stat().st_mtime) if LOG_DIR.exists() else []
            r_age = (time.time() - reviews[-1].stat().st_mtime) / 86400 if reviews else None
            add("review", "Xem lại sổ thử nghiệm hằng tuần", "ok" if r_age is not None and r_age <= 8 else "warn",
                f"{reviews[-1].name} ({r_age:.0f} ngày trước)" if reviews else "chưa có báo cáo nào")
        if t and "Wyckoff Intraday" in t and now.weekday() < 5 and now.time() >= AUTO_DONE and exp == now.date().isoformat():
            ran = conn.execute("SELECT count(*), sum(status='error') FROM job_runs WHERE job='auto_buy' AND started>=?",
                               (now.date().isoformat(),)).fetchone()
            add("auto_buy", "Tự mua thử nghiệm hôm nay", "ok" if ran[0] and not ran[1] else "warn",
                f"{ran[0]} lượt kiểm tra" + (f", {ran[1]} lượt lỗi" if ran[1] else "") if ran[0] else "chưa chạy lượt nào")
    worst = max((c["level"] for c in checks), key=LEVELS.index, default="ok")
    return dict(at=now.isoformat(timespec="minutes"), expected=exp, level=worst, checks=checks)


def notify_errors(conn, st: dict, now: dt.datetime | None = None) -> bool:
    """Có mục lỗi thì gửi Telegram, tối đa 1 lần/ngày (khóa 'health_notified' trong bảng settings). Trả đã gửi chưa."""
    errs = [c for c in st["checks"] if c["level"] == "error"]
    today = (now or now_vn()).date().isoformat()
    sent = conn.execute("SELECT value FROM settings WHERE key='health_notified'").fetchone()
    if not errs or (sent and sent[0] == today) or not notify.enabled():
        return False
    notify.send_text("🩺 Wyckoff – hệ thống có lỗi:\n" + "\n".join(f"  ⛔ {c['label']}: {c['detail']}" for c in errs)
                     + "\nXem trang Hệ thống trên web để biết chi tiết.")
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('health_notified', ?)", (today,))
    conn.commit()
    return True


def main():
    ap = argparse.ArgumentParser(description="Sức khỏe hệ thống Wyckoff")
    ap.add_argument("--notify", action="store_true", help="có mục lỗi thì gửi Telegram (tối đa 1 lần/ngày)")
    a = ap.parse_args()
    conn = connect()
    st = status(conn)
    icon = {"ok": "✅", "warn": "⚠️", "error": "⛔"}
    print(f"Sức khỏe hệ thống lúc {st['at'][11:16]} {_day(st['at'][:10])} (phiên cần có: {_day(st['expected'])}): {st['level']}")
    for c in st["checks"]:
        print(f"  {icon[c['level']]} {c['label']}: {c['detail']}")
    if a.notify:
        print("Đã gửi Telegram." if notify_errors(conn, st) else "Không gửi Telegram (không có lỗi / đã gửi hôm nay / chưa cấu hình).")


if __name__ == "__main__":
    main()
