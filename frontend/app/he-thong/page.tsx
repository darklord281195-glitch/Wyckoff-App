"use client";
import { useCallback, useEffect, useState } from "react";
import { api, day, type Health } from "@/lib/api";

const ICON: Record<Health["level"], string> = { ok: "✅", warn: "⚠️", error: "⛔" };
const TEXT: Record<Health["level"], string> = { ok: "Mọi thứ bình thường", warn: "Có mục cần xem", error: "Có lỗi cần xử lý" };

/** Sức khỏe hệ thống: quét cuối ngày, dữ liệu, lỗi tải, nguồn dự phòng, task Windows, sao lưu, Telegram. */
export default function SystemHealth() {
  const [h, setH] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    setBusy(true);
    api<Health>("/api/health").then((x) => { setH(x); setErr(null); })
      .catch((e) => setErr(String(e))).finally(() => setBusy(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <section className="card" style={{ display: "grid", gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Sức khỏe hệ thống</h2>
        <button className="btn" onClick={load} disabled={busy}>{busy ? "Đang kiểm tra…" : "Kiểm tra lại"}</button>
      </div>
      {err && <p className="down" style={{ margin: 0 }}>Không gọi được backend ({err}). Backend ở cổng 8000 có đang chạy không?</p>}
      {h && <>
        <p style={{ margin: 0 }}>
          {ICON[h.level]} <b>{TEXT[h.level]}</b>
          <span className="muted"> · kiểm tra lúc {h.at.slice(11, 16)} {day(h.at.slice(0, 10))} · phiên cần đã quét: {day(h.expected)}</span>
        </p>
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8, overflowWrap: "anywhere" }}>
          {h.checks.map((c) => (
            <li key={c.key} style={{ display: "grid", gridTemplateColumns: "24px 1fr", gap: 6 }}>
              <span aria-label={c.level}>{ICON[c.level]}</span>
              <span><b>{c.label}</b> <span className={c.level === "error" ? "down" : "muted"}>· {c.detail}</span></span>
            </li>
          ))}
        </ul>
        <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
          Task “Wyckoff Watchdog” (16:30 thứ 2–6) chạy lại kiểm tra này và gửi Telegram khi có mục ⛔, tối đa 1 lần/ngày.
          Đăng ký các task: <code>scripts\register-task.ps1</code> trên máy chạy quét. Kiểm tra tay: <code>scripts\health.bat</code>.
          Khi VNDirect lỗi, app tự lấy giá từ nguồn dự phòng DNSE (chỉ nối thêm phiên mới, phải khớp giá các phiên đã có).
        </p>
      </>}
    </section>
  );
}
