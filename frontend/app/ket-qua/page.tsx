"use client";
import { useEffect, useRef, useState } from "react";
import { createChart, ColorType, LineStyle, Time } from "lightweight-charts";
import { api, fullDate, num, type PortfolioRun } from "@/lib/api";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
// màu theo vai trò: app = nhấn, VNINDEX = trung tính, đèn = cam; chữ luôn dùng màu chữ, chấm màu chỉ để nhận diện
const SERIES = [
  { k: "app", name: "Wyckoff app", color: () => css("--accent"), dash: false },
  { k: "vni", name: "Mua-giữ VNINDEX", color: () => css("--muted"), dash: false },
  { k: "light", name: "Chỉ theo đèn", color: () => "#f59e0b", dash: true },
] as const;

/** Kết quả: backtest cấp danh mục so với mua-giữ VNINDEX và chiến lược chỉ theo đèn. */
export default function Results() {
  const [run, setRun] = useState<PortfolioRun | null | undefined>(undefined);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { api<PortfolioRun | null>("/api/backtest/portfolio").then(setRun).catch(() => setRun(null)); }, []);

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
        .setData(run.curves.map((c) => ({ time: c.d as Time, value: c[s.k] })));
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [run]);

  if (run === undefined) return <div className="card">Đang tải…</div>;
  if (run === null) return <div className="card">Chưa có kết quả. Chạy <code>.venv\Scripts\python -m app.backtest --portfolio</code> trong thư mục backend.</div>;
  const p = run.params, periods = Object.keys(run.metrics), full = run.metrics["Toàn kỳ"];
  const years = Object.keys(full.app.yearly);

  return (
    <>
      <section className="card">
        <h2>Backtest danh mục · vốn 100 triệu</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          {fullDate(p.start)} → {fullDate(p.end)} · rủi ro {num(p.risk_pct, 1)}%/lệnh, tối đa {p.max_pos} lệnh, tổng rủi ro ≤ {num(p.max_heat, 1)}% vốn,
          ẩn tín hiệu theo đèn như app · vào {p.trades_taken}/{p.trades_total} lệnh · đã tính phí, thuế, trượt giá 0,25%/chiều · chạy lúc {run.created}
        </p>
        <div className="row" style={{ gap: 16, marginBottom: 6 }}>
          {SERIES.map((s) => (
            <span key={s.k} className="row" style={{ gap: 6 }}>
              <span style={{ width: 18, height: 0, borderTop: `2px ${s.dash ? "dashed" : "solid"} ${s.color()}` }} />{s.name}
            </span>
          ))}
        </div>
        <div ref={box} style={{ width: "100%", height: 340 }} />
      </section>

      <section className="card">
        <h2>Chỉ số</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Giai đoạn</th><th>Chiến lược</th><th>Tổng</th><th>Mỗi năm</th><th>Sụt giảm lớn nhất</th>
              <th>Sharpe</th><th>Có vị thế</th><th>Số lệnh</th></tr></thead>
            <tbody>
              {periods.map((per) => SERIES.map((s, i) => {
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
                    <td className="n">{s.k === "app" ? num(m.trades ?? 0) : "–"}</td>
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
              {SERIES.map((s) => (
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
