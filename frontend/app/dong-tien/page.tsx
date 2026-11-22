"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, day, fullDate, num, pct, type Flow, type FlowRow } from "@/lib/api";

const WINDOWS = [{ s: 5, l: 20, t: "5 phiên so với 20 phiên trước" }, { s: 10, l: 20, t: "10 phiên so với 20 phiên trước" },
  { s: 20, l: 60, t: "20 phiên so với 60 phiên trước" }];
// màu theo trạng thái; luôn đi kèm chữ nên không phụ thuộc màu
const LABEL_COLOR: Record<string, string> = { "Tiền vào": "var(--up)", "Tiền rút ra": "var(--down)", "Bị xả": "#f59e0b", "Tăng thiếu lực": "var(--muted)" };
const LABEL_NOTE: Record<string, string> = {
  "Tiền vào": "tỷ trọng tăng, giá mạnh hơn VNINDEX",
  "Bị xả": "tỷ trọng tăng nhưng giá yếu hơn VNINDEX: giao dịch nhiều do bán ra",
  "Tăng thiếu lực": "giá mạnh hơn VNINDEX nhưng tỷ trọng giảm",
  "Tiền rút ra": "tỷ trọng giảm, giá yếu hơn VNINDEX",
};
const short = (s: string) => s.replace("Hàng hóa và dịch vụ công nghiệp", "HH & DV công nghiệp")
  .replace("Đồ dùng cá nhân và đồ gia dụng", "Đồ dùng cá nhân").replace("Phương tiện truyền thông", "Truyền thông");

/** 1) Chênh lệch tỷ trọng giá trị giao dịch: thanh lệch hai phía quanh 0. */
function ShareBars({ rows }: { rows: FlowRow[] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.d_share)), 0.5);
  const W = 540, L = 150, R = 50, H = 26, mid = L + (W - L - R) / 2, half = (W - L - R) / 2;
  return (
    <svg viewBox={`0 0 ${W} ${rows.length * H + 24}`} width="100%" role="img" aria-label="Chênh lệch tỷ trọng giá trị giao dịch theo ngành">
      <line x1={mid} x2={mid} y1={0} y2={rows.length * H} stroke="var(--grid)" />
      {rows.map((r, i) => {
        const w = Math.abs(r.d_share) / max * half, y = i * H + 4, pos = r.d_share >= 0;
        return (
          <g key={r.icb}>
            <title>{`${r.name}: ${pct(r.d_share, 2).replace("%", "")} điểm % (từ ${num(r.share_prev, 1)}% lên ${num(r.share, 1)}%)`}</title>
            <text x={L - 8} y={y + 13} textAnchor="end" fontSize="12" fill="var(--fg)">{short(r.name)}</text>
            <rect x={pos ? mid + 1 : mid - w - 1} y={y} width={Math.max(w, 1)} height={H - 8} rx={3}
              fill={pos ? "var(--up)" : "var(--down)"} />
            <text x={pos ? mid + w + 6 : mid - w - 6} y={y + 13} textAnchor={pos ? "start" : "end"} fontSize="11.5"
              fill="var(--muted)" className="mono">{(pos ? "+" : "") + num(r.d_share, 2)}</text>
          </g>
        );
      })}
      <text x={mid - 6} y={rows.length * H + 18} textAnchor="end" fontSize="11.5" fill="var(--muted)">← tiền rút ra</text>
      <text x={mid + 6} y={rows.length * H + 18} fontSize="11.5" fill="var(--muted)">tiền chảy vào →</text>
    </svg>
  );
}

/** 2) Bốn ô: trục ngang = chênh tỷ trọng, trục dọc = giá so với VNINDEX; cỡ chấm = tỷ trọng hiện tại. */
function Quadrant({ rows }: { rows: FlowRow[] }) {
  const W = 640, H = 420, P = 44;
  const mx = Math.max(...rows.map((r) => Math.abs(r.d_share)), 0.5) * 1.15;
  const my = Math.max(...rows.map((r) => Math.abs(r.rel)), 1) * 1.15;
  const X = (v: number) => P + (v + mx) / (2 * mx) * (W - 2 * P), Y = (v: number) => H - P - (v + my) / (2 * my) * (H - 2 * P);
  const maxShare = Math.max(...rows.map((r) => r.share));
  const corner = (x: number, y: number, t: string, anchor: "start" | "end") =>
    <text x={x} y={y} textAnchor={anchor} fontSize="12" fontWeight={600} fill={LABEL_COLOR[t]}>{t}</text>;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Tỷ trọng giao dịch so với giá theo ngành">
      <line x1={X(0)} x2={X(0)} y1={P / 2} y2={H - P} stroke="var(--grid)" />
      <line x1={P} x2={W - P} y1={Y(0)} y2={Y(0)} stroke="var(--grid)" />
      {corner(W - P, P / 2 + 10, "Tiền vào", "end")}{corner(W - P, H - P - 8, "Bị xả", "end")}
      {corner(P + 4, P / 2 + 10, "Tăng thiếu lực", "start")}{corner(P + 4, H - P - 8, "Tiền rút ra", "start")}
      <text x={W / 2} y={H - 10} textAnchor="middle" fontSize="11.5" fill="var(--muted)">Chênh tỷ trọng giá trị giao dịch (điểm %) →</text>
      <text x={14} y={H / 2} textAnchor="middle" fontSize="11.5" fill="var(--muted)" transform={`rotate(-90 14 ${H / 2})`}>
        Giá ngành so với VNINDEX (%) →</text>
      {rows.map((r) => {
        const rad = 5 + 13 * Math.sqrt(r.share / maxShare);
        // chỉ ghi tên ngành lớn hoặc nằm xa tâm, tránh chữ chồng nhau ở giữa; ngành còn lại xem bằng rê chuột
        const far = Math.abs(r.d_share) / mx > 0.3 || Math.abs(r.rel) / my > 0.3;
        return (
          <g key={r.icb}>
            <title>{`${r.name} · ${r.label}\nTỷ trọng ${num(r.share_prev, 1)}% → ${num(r.share, 1)}% (${pct(r.d_share, 2).replace("%", "")} điểm)\n`
              + `Giá ${pct(r.ret, 1)} (so VNINDEX ${pct(r.rel, 1)}) · NN ${r.fx == null ? "–" : num(r.fx, 0) + " tỷ"}`}</title>
            <circle cx={X(r.d_share)} cy={Y(r.rel)} r={rad} fill={LABEL_COLOR[r.label]} fillOpacity={0.75}
              stroke="var(--surface)" strokeWidth={2} />
            {(far || r.share >= 10) && <text x={X(r.d_share)} y={Y(r.rel) - rad - 4} textAnchor="middle" fontSize="11"
              fill="var(--fg)">{short(r.name)}</text>}
          </g>
        );
      })}
    </svg>
  );
}

/** 3) Bản đồ nhiệt: tỷ trọng mỗi tuần trừ tỷ trọng bình quân 12 tuần của ngành (điểm %). */
function Heat({ flow }: { flow: Flow }) {
  const max = Math.max(...flow.heat.flatMap((h) => h.cells.map(Math.abs)), 0.3);
  // khung rộng cố định ~ bề rộng thẻ: ô giãn theo số tuần, chữ không bị phóng to
  const W = 1160, L = 190, H = 26, C = (W - L - 4) / Math.max(1, flow.weeks.length);
  const color = (v: number) => `color-mix(in srgb, ${v >= 0 ? "var(--up)" : "var(--down)"} ${Math.round(Math.min(1, Math.abs(v) / max) * 85)}%, var(--surface))`;
  return (
    <svg viewBox={`0 0 ${W} ${flow.heat.length * H + 26}`} width="100%" role="img" aria-label="Tỷ trọng theo tuần so với bình quân 12 tuần">
      {flow.weeks.map((w, j) => <text key={w} x={L + j * C + C / 2} y={14} textAnchor="middle" fontSize="10.5" fill="var(--muted)">{day(w)}</text>)}
      {flow.heat.map((h, i) => (
        <g key={h.icb}>
          <text x={L - 8} y={26 + i * H + 15} textAnchor="end" fontSize="12" fill="var(--fg)">{short(h.name)}</text>
          {h.cells.map((v, j) => (
            <rect key={j} x={L + j * C + 1} y={22 + i * H} width={C - 2} height={H - 2} rx={3} fill={color(v)}>
              <title>{`${h.name} · tuần tới ${fullDate(flow.weeks[j])}: ${(v >= 0 ? "+" : "") + num(v, 2)} điểm % so với bình quân 12 tuần`}</title>
            </rect>
          ))}
        </g>
      ))}
    </svg>
  );
}

export default function MoneyFlow() {
  const [w, setW] = useState(0);
  const [f, setF] = useState<Flow | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const x = WINDOWS[w];
    api<Flow>(`/api/flow?short=${x.s}&long=${x.l}`).then((r) => { setF(r); setErr(null); }).catch((e) => setErr(String(e)));
  }, [w]);
  const byLabel = useMemo(() => {
    const g: Record<string, FlowRow[]> = {};
    (f?.rows ?? []).forEach((r) => { (g[r.label] ??= []).push(r); });
    return g;
  }, [f]);

  if (err) return <div className="card">Lỗi: {err}</div>;
  if (!f) return <div className="card">Đang tải…</div>;
  if (!f.rows.length) return <div className="card">{f.error ?? "Chưa có dữ liệu."}</div>;
  const chg = (f.total / f.total_prev - 1) * 100;

  return (
    <>
      <section className="card row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0 }}>Dòng tiền theo ngành</h2>
          <span className="muted">Kỳ gần {fullDate(f.start)} → {fullDate(f.end)} · so với {fullDate(f.prev_start)} → {fullDate(f.prev_end)}</span>
        </div>
        <select className="btn" value={w} onChange={(e) => setW(+e.target.value)}>
          {WINDOWS.map((x, i) => <option key={i} value={i}>{x.t}</option>)}
        </select>
      </section>

      <section className="card">
        <dl className="kv" style={{ gridTemplateColumns: "auto 1fr auto 1fr" }}>
          <dt>GT toàn thị trường</dt><dd>{num(f.total)} tỷ/phiên <span className={chg >= 0 ? "up" : "down"}>({pct(chg, 1)} so với kỳ trước)</span></dd>
          <dt>VNINDEX kỳ gần</dt><dd className={f.idx_ret >= 0 ? "up" : "down"}>{pct(f.idx_ret, 2)}</dd>
        </dl>
        <ul className="sig" style={{ margin: "10px 0 0" }}>
          {["Tiền vào", "Bị xả", "Tăng thiếu lực", "Tiền rút ra"].filter((k) => byLabel[k]?.length).map((k) => (
            <li key={k}><b style={{ color: LABEL_COLOR[k] }}>{k}</b>: {byLabel[k].map((r) => short(r.name)).join(", ")}{" "}
              <span className="muted">({LABEL_NOTE[k]})</span></li>
          ))}
        </ul>
      </section>

      <div className="grid2" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <section className="card">
          <h2>Tỷ trọng giá trị giao dịch thay đổi (điểm %)</h2>
          <ShareBars rows={f.rows} />
        </section>
        <section className="card">
          <h2>Tiền vào thật hay bị xả?</h2>
          <Quadrant rows={f.rows} />
          <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>Cỡ chấm = tỷ trọng hiện tại. Rê chuột lên chấm để xem số liệu.</p>
        </section>
      </div>

      <section className="card">
        <h2>Xoay vòng 12 tuần</h2>
        <Heat flow={f} />
        <p className="muted" style={{ margin: "6px 0 0", fontSize: 12.5 }}>
          Mỗi ô = tỷ trọng giá trị giao dịch của ngành trong tuần đó trừ bình quân 12 tuần của chính ngành. Xanh đậm dần = tiền đang dồn vào,
          đỏ đậm dần = tiền đang rời đi; một ngành chuyển từ đỏ sang xanh qua các tuần là dấu hiệu dòng tiền xoay vòng sang.
        </p>
      </section>

      <section className="card">
        <h2>Chi tiết</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Ngành</th><th>Trạng thái</th><th>Tỷ trọng</th><th>Chênh</th><th>GT/phiên</th><th>Giá</th>
              <th>So VNINDEX</th><th>NN ròng</th><th>Mã giao dịch nhiều nhất</th></tr></thead>
            <tbody>
              {f.rows.map((r) => (
                <tr key={r.icb}>
                  <td><b>{r.name}</b></td>
                  <td><span style={{ color: LABEL_COLOR[r.label], fontWeight: 600 }}>● </span>{r.label}</td>
                  <td className="n">{num(r.share_prev, 1)}% → {num(r.share, 1)}%</td>
                  <td className={`n ${r.d_share >= 0 ? "up" : "down"}`}>{(r.d_share >= 0 ? "+" : "") + num(r.d_share, 2)}</td>
                  <td className="n">{num(r.value)} tỷ <span className="muted">({r.value_chg == null ? "–" : pct(r.value_chg, 0)})</span></td>
                  <td className={`n ${r.ret >= 0 ? "up" : "down"}`}>{pct(r.ret, 1)}</td>
                  <td className={`n ${r.rel >= 0 ? "up" : "down"}`}>{pct(r.rel, 1)}</td>
                  <td className={`n ${r.fx == null ? "muted" : r.fx >= 0 ? "up" : "down"}`}>{r.fx == null ? "–" : (r.fx > 0 ? "+" : "") + num(r.fx, 0)}</td>
                  <td>{r.top.map((t, i) => <span key={t.sym}>{i ? " · " : ""}<Link href={`/symbol/${t.sym}`}>{t.sym}</Link>{" "}
                    <span className={t.ret >= 0 ? "up" : "down"} style={{ fontSize: 12 }}>{pct(t.ret, 1)}</span></span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
          Tỷ trọng = giá trị giao dịch (KL × giá) của ngành / toàn thị trường HOSE + HNX. Giá ngành = bình quân thay đổi giá các mã, trọng số theo
          giá trị giao dịch. NN ròng = khối ngoại mua ròng trong kỳ gần (tỷ đồng; chỉ mã có dữ liệu khối ngoại). Ẩn các ngành tỷ trọng dưới 0,3%.
        </p>
      </section>
    </>
  );
}
