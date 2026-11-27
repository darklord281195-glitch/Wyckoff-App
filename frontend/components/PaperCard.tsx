"use client";
import Link from "next/link";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { api, fullDate, num, price, type Paper, type PaperReview, type PaperStats } from "@/lib/api";

const r = (x: number | null | undefined) => (x == null ? "–" : (x > 0 ? "+" : "") + num(x, 2) + "R");
const cls = (x: number | null | undefined) => (x == null ? "muted" : x >= 0 ? "up" : "down");
const p = (x: number | null) => (x == null ? "–" : num(x) + "%");
const LIGHT: Record<string, string> = { green: "xanh", yellow: "vàng", red: "đỏ" };

// markdown tối giản của báo cáo: **đậm**, `mã`, tiêu đề #/##, gạch đầu dòng lồng nhau
const inline = (t: string): ReactNode[] => t.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((x, i) =>
  x.startsWith("**") ? <b key={i}>{x.slice(2, -2)}</b> : x.startsWith("`") ? <code key={i}>{x.slice(1, -1)}</code> : x);

function Md({ text }: { text: string }) {
  return <div style={{ display: "grid", gap: 4 }}>{text.split("\n").map((l, i) => {
    const h = /^(#+)\s+(.*)/.exec(l), li = /^(\s*)[-*]\s+(.*)/.exec(l), ol = /^(\s*)\d+\.\s+(.*)/.exec(l);
    if (h) return <div key={i} style={{ fontWeight: 600, marginTop: h[1].length > 1 ? 8 : 0 }}>{inline(h[2])}</div>;
    const m = li || ol;
    if (m) return <div key={i} style={{ paddingLeft: 12 + m[1].length * 8 }}>{li ? "• " : ""}{inline(ol ? l.trim() : m[2])}</div>;
    return l.trim() ? <div key={i}>{inline(l)}</div> : <Fragment key={i} />;
  })}</div>;
}

function Cells({ s }: { s: PaperStats }) {
  return <><td className="n">{s.n}</td><td className="n">{s.closed}</td><td className="n">{p(s.win)}</td>
    <td className="n">{p(s.stop)}</td><td className={`n ${cls(s.avg_r)}`}>{r(s.avg_r)}</td></>;
}

/** Sổ lệnh thử nghiệm: app tự mua lúc 14h10–14h29 khi đạt kịch bản mua đẹp, tự bán theo luật; so theo từng điều kiện. */
export default function PaperCard() {
  const [d, setD] = useState<Paper | null>(null);
  const [rv, setRv] = useState<PaperReview>(null);
  useEffect(() => {
    api<Paper>("/api/paper").then(setD).catch(() => setD(null));
    api<PaperReview>("/api/paper/review").then(setRv).catch(() => setRv(null));
  }, []);
  if (!d) return null;

  return (
    <section className="card" style={{ display: "grid", gap: 12 }}>
      <h2 style={{ margin: 0 }}>Sổ lệnh thử nghiệm · app tự mua lúc 14h10</h2>
      <p className="muted" style={{ margin: 0 }}>
        Mã đạt đủ điều kiện kịch bản mua đẹp lúc 14h10–14h29 được ghi “mua” ở giá lúc đó, rồi tự bán đúng luật (cắt lỗ, chốt T1/T2,
        dời cắt lỗ, hết 20 phiên, có T+2). Không phải lệnh thật, không tính vào Danh mục. R đã trừ phí, thuế và trượt giá.
      </p>
      {rv && <div className="notice" style={{ display: "grid", gap: 6 }}>
        <b>Xem lại gần nhất · {fullDate(`${rv.date.slice(0, 4)}-${rv.date.slice(4, 6)}-${rv.date.slice(6)}`)}</b>
        {rv.summary && <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 3 }}>
          {rv.summary.split("\n").slice(1).filter((l) => l.trim() && !l.startsWith("Báo cáo đầy đủ")).map((l, i) => <li key={i}>{l}</li>)}
        </ul>}
        <details>
          <summary style={{ cursor: "pointer" }}>Báo cáo đầy đủ</summary>
          <div style={{ marginTop: 8 }}><Md text={rv.report} /></div>
        </details>
      </div>}
      {d.summary.n === 0 ? <p className="muted" style={{ margin: 0 }}>Chưa có lệnh thử nghiệm nào. Cần task “Wyckoff Intraday” chạy trong giờ giao dịch.</p> : <>
        <div className="tbl">
          <table>
            <thead><tr><th>Nhóm</th><th>Lệnh</th><th>Đã đóng</th><th>Thắng</th><th>Cắt lỗ</th><th>R TB</th></tr></thead>
            <tbody>
              <tr><td><b>Tất cả</b></td><Cells s={d.summary} /></tr>
              {d.groups.map((g) => g.rows.map((x, i) => (
                <tr key={g.name + x.label}>
                  <td>{i === 0 && <span className="muted">{g.name}: </span>}{x.label}</td><Cells s={x} />
                </tr>
              )))}
            </tbody>
          </table>
        </div>
        <div className="tbl">
          <table>
            <thead><tr><th>Mã</th><th>Mua</th><th>Giá</th><th>Cắt lỗ</th><th>Đèn</th><th>KL</th><th>Lời/lỗ</th>
              <th>Trạng thái</th><th>R</th><th>Việc gần nhất</th></tr></thead>
            <tbody>
              {d.items.map((x) => {
                const e = x.events[x.events.length - 1];
                return (
                  <tr key={x.id}>
                    <td><Link href={`/symbol/${x.sym}`}><b>{x.sym}</b></Link> <span className="muted" style={{ fontSize: 11.5 }}>{x.kind ?? ""}</span></td>
                    <td className="n">{fullDate(x.d)} <span className="muted">{x.at}</span></td>
                    <td className="n">{price(x.entry_px)}</td>
                    <td className="n down">{price(x.stop)}</td>
                    <td>{LIGHT[x.light ?? ""] ?? "?"}</td>
                    <td className="n">{x.vx == null ? "–" : "x" + num(x.vx, 1)}</td>
                    <td className="n">{x.rr == null ? "–" : num(x.rr, 1)}</td>
                    <td>{x.status}{x.exit_why ? ` · ${x.exit_why}` : ""}{x.exit_d ? ` ${fullDate(x.exit_d)}` : ""}</td>
                    <td className={`n ${cls(x.R)}`}>{r(x.R)}</td>
                    <td style={{ whiteSpace: "normal" }} className="muted">{e ? `${fullDate(e.d)}: ${e.text}` : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </>}
    </section>
  );
}
