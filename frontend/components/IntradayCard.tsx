"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type IntradayAlert } from "@/lib/api";

// giờ VN: 14:05–14:50 thứ 2–6 thì tải lại mỗi phút (app tự mua thử nghiệm 14:10–14:29)
const live = () => { const n = new Date(Date.now() + 7 * 3600e3), m = n.getUTCHours() * 60 + n.getUTCMinutes();
  return n.getUTCDay() >= 1 && n.getUTCDay() <= 5 && m >= 14 * 60 + 5 && m <= 14 * 60 + 50; };

/** Trong phiên hôm nay: mua thử nghiệm lúc 14h10 (📒) và cảnh báo giá. */
export default function IntradayCard() {
  const [rows, setRows] = useState<IntradayAlert[]>([]);
  useEffect(() => {
    const load = () => api<IntradayAlert[]>("/api/intraday").then(setRows).catch(() => {});
    load();
    const t = setInterval(() => live() && load(), 60000);
    return () => clearInterval(t);
  }, []);
  if (!rows.length) return null;
  const buys = rows.filter((r) => r.kind.startsWith("buy"));

  return (
    <section className="card">
      <h2>Trong phiên hôm nay</h2>
      {buys.length > 0 && <p className="muted" style={{ marginTop: 0 }}>
        📒 = app tự mua thử nghiệm (không phải lệnh thật), sẽ tự bán theo luật. Kết quả ở trang{" "}
        <Link href="/ket-qua">Kết quả</Link>.</p>}
      <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
        {rows.map((r) => {
          const [icon, , ...rest] = (r.text ?? "").split(" ");    // text = "📒 MÃ giá · ..."
          return (
            <li key={r.kind + r.sym}>
              <span className="muted mono">{r.at}</span> {icon} <Link href={`/symbol/${r.sym}`}>{r.sym}</Link> {rest.join(" ")}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
