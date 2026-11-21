"use client";
import { useEffect, useRef, useState } from "react";
import {
  createChart, ColorType, CrosshairMode, LineStyle, IChartApi, SeriesMarker, Time,
} from "lightweight-charts";
import type { Analysis, Ohlcv } from "@/lib/api";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
/** ngày thứ 2 của tuần chứa d - cùng khóa nến tuần với backend (api.weekly) */
const wk = (d: string) => {
  const t = new Date(d + "T00:00:00Z");
  t.setUTCDate(t.getUTCDate() - (t.getUTCDay() + 6) % 7);
  return t.toISOString().slice(0, 10);
};

/** Nến ngày/tuần + KL + vùng SC–AR + mốc Wyckoff. Phân tích luôn theo khung ngày; khung tuần để xem bối cảnh. */
export default function WyckoffChart({ data, weekly, analysis, unit }:
  { data: Ohlcv[]; weekly?: Ohlcv[]; analysis: Analysis | null; unit: "pt" | "k" }) {
  const box = useRef<HTMLDivElement>(null);
  const [tf, setTf] = useState<"D" | "W">("D");

  useEffect(() => {
    const W = tf === "W" && !!weekly?.length;
    const rows = W ? weekly! : data;
    const k = W ? wk : (d: string) => d;              // khóa thời gian của mốc sự kiện trên khung đang xem
    if (!box.current || rows.length === 0) return;
    const muted = css("--muted"), grid = css("--grid"), accent = css("--accent");
    const up = css("--up"), down = css("--down"), surface = css("--surface");
    const chart: IChartApi = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: surface }, textColor: muted, fontFamily: css("--font") },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: grid, scaleMargins: { top: 0.08, bottom: 0.28 } },
      timeScale: { borderColor: grid },
      localization: {
        locale: "vi-VN",
        priceFormatter: (p: number) => unit === "pt"
          ? p.toLocaleString("vi-VN", { maximumFractionDigits: 2 })
          : Math.round(p * 1000).toLocaleString("vi-VN"),
      },
    });
    const candles = chart.addCandlestickSeries({
      upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down,
    });
    candles.setData(rows.map((r) => ({ time: r.d as Time, open: r.o, high: r.h, low: r.l, close: r.c })));

    const vol = chart.addHistogramSeries({
      priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false,
      priceFormat: { type: "custom", minMove: 0.01, formatter: (v: number) => v.toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " tr" },
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    const evDays = new Set(analysis?.events.map((e) => k(e.d)));
    vol.setData(rows.map((r) => ({
      time: r.d as Time, value: r.v,
      color: evDays.has(r.d) ? accent : r.c >= r.o ? up + "66" : down + "66",
    })));
    // đường KL trung bình 20 nến: cột vượt đường = KL trên TB20
    let sum = 0;
    const ma20 = rows.flatMap((r, i) => {
      sum += r.v - (i >= 20 ? rows[i - 20].v : 0);
      return i >= 19 ? [{ time: r.d as Time, value: sum / 20 }] : [];
    });
    chart.addLineSeries({
      priceScaleId: "vol", color: "#f59e0b", lineWidth: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    }).setData(ma20);

    if (analysis?.range) {
      const rg = analysis.range;
      // vùng tích lũy: tô nền SC–AR từ ngày SC tới nay, đường trần/đáy đứt nét đậm
      const days = rows.filter((r) => r.d >= k(rg.start)).map((r) => r.d as Time);
      const line = { lineWidth: 2 as const, lineStyle: LineStyle.Dashed, priceLineVisible: false, crosshairMarkerVisible: false };
      chart.addBaselineSeries({
        ...line, baseValue: { type: "price", price: rg.sup }, title: "Trần vùng (AR)",
        topLineColor: accent, topFillColor1: accent + "1f", topFillColor2: accent + "1f",
        bottomLineColor: accent, bottomFillColor1: "transparent", bottomFillColor2: "transparent",
      }).setData(days.map((time) => ({ time, value: rg.res })));
      chart.addLineSeries({ ...line, color: accent, title: "Đáy vùng (SC)" })
        .setData(days.map((time) => ({ time, value: rg.sup })));
      const p = analysis.plan;
      if (p && unit === "k") {
        const green = css("--green"), purple = "#8b5cf6";
        if (p.entry_lo) candles.createPriceLine({ price: p.entry_lo, color: green, lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "Vào" });
        if (p.entry_hi) candles.createPriceLine({ price: p.entry_hi, color: green, lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "Vào" });
        if (p.stop) candles.createPriceLine({ price: p.stop, color: down, lineStyle: LineStyle.Solid, lineWidth: 1, axisLabelVisible: true, title: "Cắt lỗ" });
        p.targets.forEach((t) => candles.createPriceLine({
          price: t.price, color: purple, lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true, title: t.k,
        }));
      }
    }
    const first = rows[0].d;
    const markers: SeriesMarker<Time>[] = (analysis?.events ?? [])
      .filter((e) => k(e.d) >= first)
      .map((e) => ({
        time: k(e.d) as Time,
        position: e.pos === "high" ? "aboveBar" : "belowBar",
        color: accent, shape: e.pos === "high" ? "arrowDown" : "arrowUp",
        // KL/TB20 là của phiên ngày, chỉ ghi trên khung ngày
        text: e.k + (e.vx && !W ? ` x${e.vx.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}` : ""),
      }));
    // mốc phân phối (màu đỏ); bỏ AR/ST để không lẫn với mốc tích lũy cùng tên
    (analysis?.distrib?.events ?? [])
      .filter((e) => k(e.d) >= first && ["BC", "UTAD", "SOW", "LPSY"].includes(e.k))
      .forEach((e) => markers.push({
        time: k(e.d) as Time, position: e.pos === "high" ? "aboveBar" : "belowBar",
        color: down, shape: e.pos === "high" ? "arrowDown" : "arrowUp", text: e.k,
      }));
    candles.setMarkers(markers.sort((a, b) => (a.time < b.time ? -1 : 1)));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, weekly, tf, analysis, unit]);

  return (
    <>
      <div className="tabs" style={{ marginBottom: 8 }}>
        <button className={tf === "D" ? "on" : ""} onClick={() => setTf("D")}>Ngày</button>
        <button className={tf === "W" ? "on" : ""} onClick={() => setTf("W")} disabled={!weekly?.length}>Tuần</button>
        {tf === "W" && <span className="muted" style={{ fontSize: 12.5, marginLeft: 8 }}>
          ~3 năm · mốc Wyckoff tính theo ngày, gắn vào tuần chứa ngày đó</span>}
      </div>
      <div ref={box} style={{ width: "100%", height: 460 }} />
    </>
  );
}
