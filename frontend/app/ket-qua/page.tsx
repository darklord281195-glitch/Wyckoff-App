"use client";
import { useEffect, useRef, useState } from "react";
import { createChart, ColorType, LineStyle, Time } from "lightweight-charts";
import { api, fullDate, num, type PortfolioRun } from "@/lib/api";
import ForwardCard from "@/components/ForwardCard";
import PaperCard from "@/components/PaperCard";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
// màu theo vai trò: app = nhấn, VNINDEX = trung tính, đèn = cam; chữ luôn dùng màu chữ, chấm màu chỉ để nhận diện
const BASE = [
  { k: "app", name: "Wyckoff app", color: () => css("--accent"), dash: false },
  { k: "vni", name: "Mua-giữ VNINDEX", color: () => css("--muted"), dash: false },
  { k: "light", name: "Chỉ theo đèn", color: () => "#f59e0b", dash: true },
];
const PICK_COLOR = () => "#10b981";                 // đường cách chia vốn đang chọn

/** Kết quả: backtest cấp danh mục so với mua-giữ VNINDEX, chiến lược chỉ theo đèn và các cách chia vốn lõi–vệ tinh. */
export default function Results() {
  const [run, setRun] = useState<PortfolioRun | null | undefined>(undefined);
  const [pick, setPick] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { api<PortfolioRun | null>("/api/backtest/portfolio").then((r) => { setRun(r); setPick(r?.params.best ?? null); })
    .catch(() => setRun(null)); }, []);
  const names = run?.params.names ?? {};
  const SERIES = [...BASE, ...(pick && run?.curves[0]?.[pick] != null
    ? [{ k: pick, name: names[pick] ?? pick, color: PICK_COLOR, dash: false }] : [])];

  useEffect(() => {
    if (!box.current || !run) return;
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--surface") }, textColor: css("--muted"), fontFamily: css("--font") },
      grid: { vertLines: { visible: false }, horzLines: { color: css("--grid") } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderColor: css("--grid") },
      localization: { locale: "vi-VN", priceFormatter: (p: number) => num(p, 0) },
    });
    for (const s of SERIES) {
      chart.addLineSeries({ color: s.color(), lineWidth: 2, lineStyle: s.dash ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false, lastValueVisible: true, title: "" })
        .setData(run.curves.map((c) => ({ time: String(c.d) as Time, value: Number(c[s.k]) })));
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [run, pick]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (run === undefined) return <div className="card">Đang tải…</div>;
  if (run === null) return <><PaperCard /><ForwardCard /><div className="card">Chưa có kết quả backtest danh mục. Chạy <code>.venv\Scripts\python -m app.backtest --portfolio</code> trong thư mục backend.</div></>;
  const p = run.params, periods = Object.keys(run.metrics), full = run.metrics["Toàn kỳ"];
  const years = Object.keys(full.app.yearly);
  const ranking = p.ranking ?? [];
  const variants = ranking.filter((x) => x.k.startsWith("cs_") || x.k === "app_idle");
  const winner = ranking.find((x) => x.both);
  const cagr = (per: string, k: string) => run.metrics[per]?.[k]?.cagr;
  const pctCell = (v: number | undefined, sign = true) => v == null ? <td className="n">–</td>
    : <td className={`n ${v >= 0 ? "up" : "down"}`}>{sign && v > 0 ? "+" : ""}{num(v, 1)}%</td>;

  return (
    <>
      <PaperCard />
      <ForwardCard />

      <section className="card">
        <h2>Backtest danh mục · vốn 100 triệu</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          {fullDate(p.start)} → {fullDate(p.end)} · rủi ro {num(p.risk_pct, 1)}%/lệnh, tối đa {p.max_pos} lệnh, tổng rủi ro ≤ {num(p.max_heat, 1)}% vốn,
          ẩn tín hiệu theo đèn như app · vào {p.trades_taken}/{p.trades_total} lệnh · đã tính phí, thuế,{" "}
          {p.slip != null ? `trượt giá tự tính TB ${num(p.slip, 2)}%/chiều` : "trượt giá 0,25%/chiều"} · chạy lúc {run.created}
        </p>
        <div className="row" style={{ gap: 16, marginBottom: 6, flexWrap: "wrap" }}>
          {SERIES.map((s) => (
            <span key={s.k} className="row" style={{ gap: 6 }}>
              <span style={{ width: 18, height: 0, borderTop: `2px ${s.dash ? "dashed" : "solid"} ${s.color()}` }} />{s.name}
            </span>
          ))}
          {variants.length > 0 && (
            <label className="row muted" style={{ gap: 6 }}>Cách chia vốn:
              <select className="btn" value={pick ?? ""} onChange={(e) => setPick(e.target.value || null)}>
                <option value="">(không vẽ)</option>
                {variants.map((x) => <option key={x.k} value={x.k}>{names[x.k] ?? x.k}</option>)}
              </select>
            </label>
          )}
        </div>
        <div ref={box} style={{ width: "100%", height: 340 }} />
      </section>

      {variants.length > 0 && (
        <section className="card">
          <h2>Chia vốn: lõi chỉ số + vệ tinh app</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            App chỉ có cổ phiếu khoảng {num(full.app.exposure)}% thời gian. Thử để một phần vốn cố định ở chỉ số (mua-giữ VNINDEX, hoặc VNINDEX
            theo đèn), phần còn lại theo app, tái cân bằng đầu mỗi tháng; hoặc để tiền nhàn rỗi của app nằm ở chỉ số khi đèn không đỏ.
            Xếp theo mức hơn/kém mua-giữ ở giai đoạn <b>tệ hơn</b> trong hai giai đoạn (một cách chỉ đáng dùng khi tốt ở cả hai).
          </p>
          <div className="tbl">
            <table>
              <thead><tr><th>Cách chia vốn</th><th>2019–23 /năm</th><th>2024–26 /năm</th><th>Toàn kỳ /năm</th>
                <th>Sụt giảm lớn nhất</th><th>Sharpe</th><th>So với mua-giữ (giai đoạn tệ hơn)</th></tr></thead>
              <tbody>
                <tr style={{ background: "var(--grid)" }}>
                  <td>Mua-giữ VNINDEX (mốc so sánh)</td>
                  {pctCell(cagr("2019–23", "vni"))}{pctCell(cagr("2024–26", "vni"))}{pctCell(cagr("Toàn kỳ", "vni"))}
                  <td className="n down">{num(full.vni.mdd, 1)}%</td><td className="n">{full.vni.sharpe == null ? "–" : num(full.vni.sharpe, 2)}</td><td>–</td>
                </tr>
                {ranking.map((x) => (
                  <tr key={x.k} style={x.k === p.best ? { fontWeight: 600 } : undefined}>
                    <td>{names[x.k] ?? x.k}{x.k === p.best ? " ★" : ""}</td>
                    {pctCell(cagr("2019–23", x.k))}{pctCell(cagr("2024–26", x.k))}{pctCell(cagr("Toàn kỳ", x.k))}
                    <td className={`n down`}>{num(full[x.k].mdd, 1)}%{x.mdd_better ? " ✓" : ""}</td>
                    <td className="n">{full[x.k].sharpe == null ? "–" : num(full[x.k].sharpe, 2)}</td>
                    <td className={`n ${x.worst >= 0 ? "up" : "down"}`}>{x.worst > 0 ? "+" : ""}{num(x.worst, 1)} điểm %/năm{x.both ? " · thắng cả hai" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ margin: "8px 0 0" }}>
            {winner ? <>→ <b>{names[winner.k] ?? winner.k}</b> thắng mua-giữ ở cả hai giai đoạn.</>
              : <>→ Chưa cách nào thắng mua-giữ VNINDEX ở <b>cả hai</b> giai đoạn. Gần nhất: <b>{names[ranking[0]?.k] ?? ranking[0]?.k}</b>
                {" "}({num(ranking[0]?.worst ?? 0, 1)} điểm %/năm ở giai đoạn tệ hơn).</>}
          </p>
          <p className="muted" style={{ margin: "4px 0 0", fontSize: 12.5 }}>
            ★ = đang vẽ trên biểu đồ. ✓ = sụt giảm lớn nhất nhỏ hơn mua-giữ. Phí mua/bán chỉ số {num(p.switch_cost ?? 0.25, 2)}% mỗi lần đổi, tái cân bằng,
            rút/nộp tiền. VNINDEX là chỉ số giá (chưa gồm cổ tức ~1–2%/năm); quỹ ETF thật có thêm phí quản lý và sai số bám chỉ số.
          </p>
        </section>
      )}

      <section className="card">
        <h2>Chỉ số</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Giai đoạn</th><th>Chiến lược</th><th>Tổng</th><th>Mỗi năm</th><th>Sụt giảm lớn nhất</th>
              <th>Sharpe</th><th>Có vị thế</th><th>Số lệnh</th></tr></thead>
            <tbody>
              {periods.map((per) => SERIES.filter((s) => run.metrics[per][s.k]).map((s, i) => {
                const m = run.metrics[per][s.k];
                return (
                  <tr key={per + s.k} style={i === 0 ? { borderTop: "2px solid var(--grid)" } : undefined}>
                    <td>{i === 0 ? <b>{per}</b> : ""}</td>
                    <td>{s.name}</td>
                    <td className={`n ${m.total >= 0 ? "up" : "down"}`}>{num(m.total, 1)}%</td>
                    <td className={`n ${m.cagr >= 0 ? "up" : "down"}`}>{num(m.cagr, 1)}%</td>
                    <td className="n down">{num(m.mdd, 1)}%</td>
                    <td className="n">{m.sharpe == null ? "–" : num(m.sharpe, 2)}</td>
                    <td className="n">{num(m.exposure)}%</td>
                    <td className="n">{s.k === "app" || s.k === "app_idle" ? num(run.metrics[per].app.trades ?? 0) : "–"}</td>
                  </tr>
                );
              }))}
            </tbody>
          </table>
        </div>
        <h2 style={{ marginTop: 16 }}>Lợi nhuận từng năm</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Chiến lược</th>{years.map((y) => <th key={y}>{y}</th>)}</tr></thead>
            <tbody>
              {SERIES.filter((s) => full[s.k]).map((s) => (
                <tr key={s.k}><td>{s.name}</td>
                  {years.map((y) => { const v = full[s.k].yearly[y]; return <td key={y} className={`n ${v >= 0 ? "up" : "down"}`}>{num(v, 1)}%</td>; })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
          Mỗi năm = lợi nhuận kép hằng năm. Sụt giảm lớn nhất = mức giảm sâu nhất từ đỉnh vốn. Sharpe = lợi nhuận trên biến động (năm hóa).
          Có vị thế = % số phiên có tiền trong cổ phiếu. Chỉ theo đèn = giữ VNINDEX khi đèn không đỏ, tiền mặt khi đỏ.
          Giới hạn: chỉ có mã đang niêm yết; bán từng phần được gộp ở ngày thoát cuối.
        </p>
      </section>
    </>
  );
}
