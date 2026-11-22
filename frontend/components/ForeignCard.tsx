"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { createChart, ColorType, IChartApi, Time } from "lightweight-charts";
import { day, fullDate, num, type Foreign } from "@/lib/api";

const RANGES = [10, 30, 50, 70, 90];
const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const ty = (x: number, d = 1) => (x > 0 ? "+" : "") + num(x, d);          // tỷ đồng có dấu

/** Giao dịch khối ngoại: cột giá trị mua ròng từng phiên (xanh mua ròng, đỏ bán ròng) + tổng hợp theo khoảng. */
export default function ForeignCard({ rows, error }: { rows: Foreign[]; error?: string | null }) {
  const [n, setN] = useState(10);
  const box = useRef<HTMLDivElement>(null);
  // cột đang rê chuột: x = tâm cột, w = bề rộng cột (px trong khung biểu đồ)
  const [hover, setHover] = useState<{ r: Foreign; x: number; w: number } | null>(null);
  const view = useMemo(() => rows.slice(-n), [rows, n]);

  useEffect(() => {
    if (!box.current || !view.length) return;
    const muted = css("--muted"), grid = css("--grid"), up = css("--up"), down = css("--down");
    const chart: IChartApi = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--surface") }, textColor: muted, fontFamily: css("--font") },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderColor: grid, fixLeftEdge: true, fixRightEdge: true },
      // tắt đường dóng mặc định: dùng dải nền + tooltip riêng
      crosshair: { vertLine: { visible: false, labelVisible: false }, horzLine: { visible: false, labelVisible: false } },
      handleScroll: false, handleScale: false,
      localization: { locale: "vi-VN", priceFormatter: (p: number) => num(p, Math.abs(p) < 10 ? 1 : 0) },
    });
    const bars = chart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    bars.setData(view.map((r) => ({ time: r.d as Time, value: r.net, color: r.net >= 0 ? up : down })));
    chart.timeScale().fitContent();
    const byDay = new Map(view.map((r) => [r.d, r]));
    // thời gian dạng "YYYY-MM-DD" được thư viện trả lại thành {year, month, day}
    const iso = (t: Time) => typeof t === "string" ? t : typeof t === "number" ? new Date(t * 1000).toISOString().slice(0, 10)
      : `${t.year}-${String(t.month).padStart(2, "0")}-${String(t.day).padStart(2, "0")}`;
    chart.subscribeCrosshairMove((p) => {
      const r = p.time ? byDay.get(iso(p.time)) : undefined;
      const x = p.time ? chart.timeScale().timeToCoordinate(p.time) : null;
      setHover(r && x != null ? { r, x, w: chart.timeScale().options().barSpacing } : null);
    });
    return () => chart.remove();
  }, [view]);

  if (error && !rows.length) return <section className="card"><h2>Khối ngoại</h2>
    <p className="muted">Không tải được dữ liệu khối ngoại ({error}).</p></section>;
  if (!rows.length) return null;

  const buy = view.reduce((s, r) => s + r.buy, 0), sell = view.reduce((s, r) => s + r.sell, 0), net = buy - sell;
  const nUp = view.filter((r) => r.net > 0).length, nDown = view.filter((r) => r.net < 0).length;
  const last = view[view.length - 1];
  const room = last.total_room ? (last.room ?? 0) / last.total_room * 100 : null;
  const tipW = 210;                                     // bề rộng tooltip; lật sang trái khi sát mép phải

  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Khối ngoại · giá trị mua ròng (tỷ đồng)</h2>
        <div className="tabs">
          {RANGES.map((x) => (
            <button key={x} className={n === x ? "on" : ""} onClick={() => setN(x)} disabled={rows.length < Math.min(x, 10)}>
              {x} phiên</button>
          ))}
        </div>
      </div>
      <div style={{ position: "relative" }} onMouseLeave={() => setHover(null)}>
        <div ref={box} style={{ width: "100%", height: 220 }} />
        {hover && <>
          <div style={{   // dải nền làm nổi cột đang rê chuột
            position: "absolute", top: 0, bottom: 28, left: hover.x - hover.w / 2, width: hover.w,
            background: "var(--muted)", opacity: 0.15, pointerEvents: "none", zIndex: 4,   // trên canvas biểu đồ (z-index 3)
          }} />
          <div className="fx-tip" style={{
            left: Math.max(4, hover.x + hover.w / 2 + tipW + 8 > (box.current?.clientWidth ?? 0)
              ? hover.x - hover.w / 2 - tipW - 6 : hover.x + hover.w / 2 + 6),
            width: tipW,
          }}>
            <div>Ngày: {fullDate(hover.r.d)}</div>
            <div>Giá trị mua ròng: <b className={hover.r.net >= 0 ? "up" : "down"}>{num(hover.r.net, 2)} tỷ</b></div>
            <div className="muted">Mua {num(hover.r.buy, 2)} · bán {num(hover.r.sell, 2)} tỷ</div>
          </div>
        </>}
      </div>
      <dl className="kv" style={{ marginTop: 10, gridTemplateColumns: "auto 1fr auto 1fr" }}>
        <dt>Ròng {view.length} phiên</dt><dd className={net >= 0 ? "up" : "down"}>{ty(net)} tỷ</dd>
        <dt>Mua / bán</dt><dd>{num(buy, 1)} / {num(sell, 1)} tỷ</dd>
        <dt>Phiên mua ròng</dt><dd>{nUp} <span className="muted">· bán ròng {nDown}</span></dd>
        <dt>Room còn lại</dt><dd>{room == null ? "–" : num(room, 1) + "%"}</dd>
      </dl>
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
        Từ {day(view[0].d)} tới {day(last.d)} · nguồn VNDirect · rê chuột lên cột để xem từng phiên
      </p>
    </section>
  );
}
