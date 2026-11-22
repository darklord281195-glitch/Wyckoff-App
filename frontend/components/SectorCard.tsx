"use client";
import { useEffect, useMemo, useState } from "react";
import { api, num, pct, type SectorRow } from "@/lib/api";

type Key = "name" | "n" | "rs20" | "rs60" | "pct_d" | "fx10";

/** Sức mạnh ngành ICB tại phiên đang xem; bấm một ngành để lọc bảng mã theo ngành đó. */
export default function SectorCard({ date, active, onPick }: {
  date: string | null; active: string; onPick: (group: string) => void;
}) {
  const [rows, setRows] = useState<SectorRow[]>([]);
  const [sort, setSort] = useState<{ k: Key; desc: boolean }>({ k: "rs20", desc: true });
  useEffect(() => {
    if (!date) return;
    api<{ rows: SectorRow[] }>("/api/sectors?date=" + date).then((x) => setRows(x.rows)).catch(() => setRows([]));
  }, [date]);
  const view = useMemo(() => [...rows].sort((a, b) => {
    const x = a[sort.k] ?? -1e9, y = b[sort.k] ?? -1e9;
    const c = x < y ? -1 : x > y ? 1 : 0;
    return sort.desc ? -c : c;
  }), [rows, sort]);
  if (!rows.length) return null;
  const th = (k: Key, label: string) => (
    <th onClick={() => setSort((s) => ({ k, desc: s.k === k ? !s.desc : k !== "name" }))}>
      {label}{sort.k === k ? (sort.desc ? " ▼" : " ▲") : ""}</th>
  );

  return (
    <section className="card">
      <h2>Ngành dẫn dắt</h2>
      <div className="tbl">
        <table>
          <thead><tr>{th("name", "Ngành")}{th("n", "Số mã")}{th("rs20", "RS20")}{th("rs60", "RS60")}
            {th("pct_d", "% Pha D / sát trần")}{th("fx10", "NN 10p (tỷ)")}</tr></thead>
          <tbody>
            {view.map((r) => {
              const g = "icb:" + r.icb;
              return (
                <tr key={r.icb} onClick={() => onPick(active === g ? "all" : g)} style={{ cursor: "pointer" }}
                  className={active === g ? "on" : ""} title="Bấm để lọc bảng mã theo ngành này (bấm lại để bỏ lọc)">
                  <td><b>{r.name}</b>{active === g ? " ✓" : ""}</td>
                  <td className="n">{r.n}</td>
                  <td className={`n ${(r.rs20 ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.rs20)}</td>
                  <td className={`n ${(r.rs60 ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.rs60)}</td>
                  <td className="n">{num(r.pct_d)}%</td>
                  <td className={`n ${r.fx10 == null ? "muted" : r.fx10 >= 0 ? "up" : "down"}`}>
                    {r.fx10 == null ? "–" : (r.fx10 > 0 ? "+" : "") + num(r.fx10, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
        Tính trên các mã GT ≥ 10 tỷ, ngành có ít nhất 3 mã. RS = trung vị chênh lệch % so với VNINDEX.
        Chỉ để xem bối cảnh: backtest 2019–2026 không thấy mua mã thuộc ngành mạnh cho kết quả tốt hơn (2024–26 còn kém hơn).
      </p>
    </section>
  );
}
