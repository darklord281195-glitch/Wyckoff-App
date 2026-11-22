"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fullDate, num, price, type Journal } from "@/lib/api";

const r = (x: number | null | undefined) => (x == null ? "–" : (x > 0 ? "+" : "") + num(x, 2) + "R");
const cls = (x: number | null | undefined) => (x == null ? "muted" : x >= 0 ? "up" : "down");

/** Nhật ký: R thật của bạn so với R nếu làm đúng luật, cờ vi phạm kỷ luật lúc mua và lúc bán. */
export default function JournalCard({ reload }: { reload: number }) {
  const [j, setJ] = useState<Journal | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Journal>("/api/journal").then((x) => { setJ(x); setErr(null); }).catch((e) => setErr(String(e))); }, [reload]);

  if (err) return <section className="card"><h2>Nhật ký</h2><p className="muted">Lỗi: {err}</p></section>;
  if (!j) return null;
  const s = j.summary;

  return (
    <section className="card" style={{ display: "grid", gap: 12 }}>
      <h2 style={{ margin: 0 }}>Nhật ký & kỷ luật</h2>
      {j.items.length === 0 ? <p className="muted" style={{ margin: 0 }}>
        Chưa có lệnh. Ghi nhận lệnh mua ở trang mã và các lần bán ở bảng trên, nhật ký sẽ so kết quả của bạn với luật.</p> : <>
        <dl className="kv" style={{ gridTemplateColumns: "auto 1fr auto 1fr" }}>
          <dt>Lệnh đã đóng</dt><dd>{s.n} <span className="muted">· đang mở {s.open}</span></dd>
          <dt>Thắng</dt><dd>{s.win == null ? "–" : num(s.win) + "%"}</dd>
          <dt>R TB của bạn</dt><dd className={cls(s.avg_real)}>{r(s.avg_real)}</dd>
          <dt>Nếu làm đúng luật</dt><dd className={cls(s.avg_rule)}>{r(s.avg_rule)}
            {s.backtest_avg_r != null && <span className="muted"> · backtest {r(s.backtest_avg_r)}</span>}</dd>
          <dt>Lệnh có vi phạm</dt><dd>{s.n_flagged}</dd>
          <dt>R mất do vi phạm</dt><dd className={cls(s.r_lost)}>{r(s.r_lost)}</dd>
        </dl>
        {Object.keys(s.flag_counts).length > 0 && <p style={{ margin: 0 }}>
          {Object.entries(s.flag_counts).map(([k, v]) => <span key={k} className="pill" style={{ marginRight: 6 }}>{k} ×{v}</span>)}
        </p>}
        <div className="tbl">
          <table>
            <thead><tr><th>Mã</th><th>Mua</th><th>Giá</th><th>Cắt lỗ đầu</th><th>Trạng thái</th>
              <th>R thật</th><th>R theo luật</th><th>Chênh</th><th>Cờ</th></tr></thead>
            <tbody>
              {j.items.map((x) => (
                <tr key={x.id}>
                  <td><Link href={`/symbol/${x.sym}`}><b>{x.sym}</b></Link> <span className="muted" style={{ fontSize: 11.5 }}>{x.kind ?? ""}</span></td>
                  <td className="n">{fullDate(x.entry_d)}</td>
                  <td className="n">{price(x.entry_px)}</td>
                  <td className="n down">{price(x.stop0)}</td>
                  <td>{x.status === "open" ? "đang mở" : `đã bán ${x.last_sale ? fullDate(x.last_sale) : ""}`}</td>
                  <td className={`n ${cls(x.r_real)}`}>{r(x.r_real)}</td>
                  <td className={`n ${cls(x.r_rule)}`}>{r(x.r_rule)}{x.rule_done ? "" : "*"}</td>
                  <td className={`n ${cls(x.diff)}`}>{r(x.diff)}</td>
                  <td style={{ whiteSpace: "normal" }}>{x.flags.length ? x.flags.map((f) => <span key={f} className="pill down" style={{ marginRight: 4 }}>{f}</span>) : <span className="up">✓</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>}
      <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
        R = lãi/lỗ sau phí chia rủi ro lúc mua (giá mua − cắt lỗ đầu); lệnh đang mở tính phần chưa bán theo giá hiện tại.
        R theo luật = cùng điểm mua, bán đúng luật (cắt lỗ, chốt T1/T2, dời cắt lỗ, hết 20 phiên); * = luật chưa bán hết.
        Cờ lúc mua: ngoài vùng vào, đèn đỏ, lời/lỗ &lt; 2. Cờ lúc bán: cắt lỗ trễ (quá 2 phiên sau tín hiệu), giữ quá hạn, bán sớm.
      </p>
    </section>
  );
}
