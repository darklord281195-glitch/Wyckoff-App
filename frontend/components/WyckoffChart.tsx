"use client";
import { useEffect, useRef } from "react";
import {
  createChart, ColorType, CrosshairMode, LineStyle, IChartApi, SeriesMarker, Time,
} from "lightweight-charts";
import type { Analysis, Ohlcv } from "@/lib/api";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Nến + KL + vùng SC–AR (price lines) + chấm sự kiện Wyckoff. */
export default function WyckoffChart({ data, analysis, unit }: { data: Ohlcv[]; analysis: Analysis | null; unit: "pt" | "k" }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!box.current || data.length === 0) return;
    const fg = css("--fg"), muted = css("--muted"), grid = css("--grid"), accent = css("--accent");
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
    candles.setData(data.map((r) => ({ time: r.d as Time, open: r.o, high: r.h, low: r.l, close: r.c })));

    const vol = chart.addHistogramSeries({
      priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false,
      priceFormat: { type: "custom", minMove: 0.01, formatter: (v: number) => v.toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " tr" },
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    const evDays = new Set(analysis?.events.map((e) => e.d));
    vol.setData(data.map((r) => ({
      time: r.d as Time, value: r.v,
      color: evDays.has(r.d) ? accent : r.c >= r.o ? up + "66" : down + "66",
    })));
    // đường KL trung bình 20 phiên: cột vượt đường = KL trên TB20
    let sum = 0;
    const ma20 = data.flatMap((r, i) => {
      sum += r.v - (i >= 20 ? data[i - 20].v : 0);
      return i >= 19 ? [{ time: r.d as Time, value: sum / 20 }] : [];
    });
    chart.addLineSeries({
      priceScaleId: "vol", color: "#f59e0b", lineWidth: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    }).setData(ma20);

    if (analysis?.range) {
      const rg = analysis.range;
      // vùng tích lũy: tô nền SC–AR từ ngày SC tới nay, đường trần/đáy đứt nét đậm
      const days = data.filter((r) => r.d >= rg.start).map((r) => r.d as Time);
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
    const first = data[0].d;
    const markers: SeriesMarker<Time>[] = (analysis?.events ?? [])
      .filter((e) => e.d >= first)
      .map((e) => ({
        time: e.d as Time,
        position: e.pos === "high" ? "aboveBar" : "belowBar",
        color: accent, shape: e.pos === "high" ? "arrowDown" : "arrowUp",
        text: e.k + (e.vx ? ` x${e.vx.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}` : ""),
      }));
    // mốc phân phối (màu đỏ); bỏ AR/ST để không lẫn với mốc tích lũy cùng tên
    (analysis?.distrib?.events ?? [])
      .filter((e) => e.d >= first && ["BC", "UTAD", "SOW", "LPSY"].includes(e.k))
      .forEach((e) => markers.push({
        time: e.d as Time, position: e.pos === "high" ? "aboveBar" : "belowBar",
        color: down, shape: e.pos === "high" ? "arrowDown" : "arrowUp", text: e.k,
      }));
    candles.setMarkers(markers.sort((a, b) => (a.time < b.time ? -1 : 1)));
    chart.timeScale().fitContent();
    void fg;
    return () => chart.remove();
  }, [data, analysis, unit]);

  return <div ref={box} style={{ width: "100%", height: 460 }} />;
}
