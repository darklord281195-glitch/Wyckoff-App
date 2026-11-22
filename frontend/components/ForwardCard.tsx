"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fullDate, num, price, type Forward } from "@/lib/api";

const r = (x: number | null | undefined) => (x == null ? "–" : (x > 0 ? "+" : "") + num(x, 2) + "R");
const cls = (x: number | null | undefined) => (x == null ? "muted" : x >= 0 ? "up" : "down");

/** Tín hiệu mua đã báo, chấm theo đúng luật backtest: khớp lệnh trong 10 phiên, bán theo luật, R sau phí + trượt giá. */
export default function ForwardCard() {
  const [all, setAll] = useState(false);                 // gồm cả tín hiệu tạo lại bằng scan --from
  const [f, setF] = useState<Forward | null>(null);
  useEffect(() => { api<Forward>("/api/forward?live=" + (all ? 0 : 1)).then(setF).catch(() => setF(null)); }, [all]);
  if (!f) return null;
  const s = f.summary;

  return (
    <section className="card" style={{ display: "grid", gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Tín hiệu đã báo · chấm điểm thật</h2>
        <label className="muted"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />{" "}
          gồm tín hiệu tạo lại (scan --from)</label>
      </div>
      {s.n === 0 ? <p className="muted" style={{ margin: 0 }}>
        Chưa có tín hiệu mua {all ? "" : "thật "}nào. Mỗi tín hiệu mua được báo từ các lần quét cuối ngày sẽ được chấm tự động:
        có khớp vùng vào trong 10 phiên không, rồi bán theo luật thì được bao nhiêu R. Khi đèn đỏ, app ẩn mọi tín hiệu mua nên sẽ không có gì để chấm.
      </p> : <>
        <dl className="kv" style={{ gridTemplateColumns: "auto 1fr auto 1fr" }}>
          <dt>Tín hiệu</dt><dd>{s.n} <span className="muted">({s.first && fullDate(s.first)} → {s.last && fullDate(s.last)})</span></dd>
          <dt>Khớp lệnh</dt><dd>{s.filled}{s.fill_rate != null ? ` (${s.fill_rate}%)` : ""} <span className="muted">· chờ khớp {s.pending}</span></dd>
          <dt>Đã đóng</dt><dd>{s.closed}{s.win != null ? <span className="muted"> · thắng {s.win}%</span> : ""}</dd>
          <dt>R TB đã đóng</dt><dd className={cls(s.avg_r)}>{r(s.avg_r)}
            {s.backtest_avg_r != null && <span className="muted"> · backtest {r(s.backtest_avg_r)}</span>}</dd>
          <dt>Tổng R (kể cả đang giữ)</dt><dd className={cls(s.sum_r)}>{r(s.sum_r)}</dd>
        </dl>
        <div className="tbl">
          <table>
            <thead><tr><th>Ngày báo</th><th>Mã</th><th>Tín hiệu</th><th>Vùng vào</th><th>Cắt lỗ</th>
              <th>Trạng thái</th><th>Khớp</th><th>Thoát</th><th>R</th></tr></thead>
            <tbody>
              {f.items.map((x) => (
                <tr key={x.date + x.sym + x.kind}>
                  <td className="n">{fullDate(x.date)}{x.replay ? <span className="muted" title="tạo lại bằng scan --from"> ↺</span> : ""}</td>
                  <td><Link href={`/symbol/${x.sym}?at=${x.date}`}><b>{x.sym}</b></Link></td>
                  <td><span className="pill">{x.kind}</span></td>
                  <td className="n">{x.entry_lo ? `${price(x.entry_lo)}–${price(x.entry_hi)}` : "–"}</td>
                  <td className="n down">{price(x.stop)}</td>
                  <td>{x.status}</td>
                  <td className="n">{x.entry_d ? `${fullDate(x.entry_d)} · ${price(x.entry)}` : "–"}</td>
                  <td>{x.exit_d ? `${fullDate(x.exit_d)} · ${x.why}` : "–"}</td>
                  <td className={`n ${cls(x.R)}`}>{r(x.R)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>}
      <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
        Chỉ tính lần báo đầu của mỗi tín hiệu mua (không tính các ngày lặp lại). Luật giống hệt backtest, nên sau vài chục tín hiệu
        thật có thể so trực tiếp với R TB backtest để biết hệ thống còn hoạt động như kỳ vọng không. ↺ = phiên tạo lại.
      </p>
    </section>
  );
}
