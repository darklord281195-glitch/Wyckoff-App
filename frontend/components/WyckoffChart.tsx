"use client";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import {
  createChart, ColorType, CrosshairMode, LineStyle, IChartApi, SeriesMarker, Time,
} from "lightweight-charts";
import { num, type Analysis, type Ohlcv, type Plan, type PlanStats } from "@/lib/api";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
type Tf = "D" | "W";
const TF_LABEL: Record<Tf, string> = { D: "Ngày", W: "Tuần" };
/** khóa nến của ngày d trên từng khung (tuần = ngày thứ 2 của tuần) */
const KEY: Record<Tf, (d: string) => string> = {
  D: (d) => d,
  W: (d) => {
    const t = new Date(d + "T00:00:00Z");
    t.setUTCDate(t.getUTCDate() - (t.getUTCDay() + 6) % 7);
    return t.toISOString().slice(0, 10);
  },
};
/** số nến hiện sẵn khi mở khung (≈1 năm / 3 năm); kéo/zoom để xem thêm */
const SHOW: Record<Tf, number> = { D: 260, W: 156 };

/** gộp nến ngày thành nến tuần */
function group(data: Ohlcv[], key: (d: string) => string): Ohlcv[] {
  const out: Ohlcv[] = [];
  for (const r of data) {
    const d = key(r.d), w = out[out.length - 1];
    if (w && w.d === d) { w.h = Math.max(w.h, r.h); w.l = Math.min(w.l, r.l); w.c = r.c; w.v += r.v; }
    else out.push({ ...r, d });
  }
  return out;
}

type Node = { n: number; price: number; label?: string };   // n = số phiên tính từ phiên phân tích
const SC_KEY = "wyckoff.scenario";                          // localStorage: bật/tắt kịch bản

/** Kịch bản minh họa theo kế hoạch: nhánh thành công (vào -> T1 -> T2...) và nhánh hỏng (vào -> cắt lỗ).
 *  Thời gian ước lượng: vào sau 1 phiên nếu đang trong vùng, không thì 5 phiên; T1 trong ¾ hạn time_stop; mỗi mục tiêu sau +15 phiên. */
function scenario(p: Plan | null | undefined, c: number): { ok: Node[]; fail: Node[] } | null {
  if (!p?.entry_lo || !p.stop || !p.targets.length) return null;
  const entry = p.entry_hi ? (p.entry_lo + p.entry_hi) / 2 : p.entry_lo;
  const nIn = p.in_zone ? 1 : 5;
  const ok: Node[] = [{ n: 0, price: c }, { n: nIn, price: entry, label: "Vào" }];
  let n = nIn + Math.round((p.time_stop || 20) * 0.75);
  for (const t of [...p.targets].sort((a, b) => a.price - b.price)) {
    if (t.price <= entry) continue;
    ok.push({ n, price: t.price, label: t.k }); n += 15;
  }
  if (ok.length < 3) return null;
  return { ok, fail: [{ n: nIn, price: entry }, { n: nIn + 5, price: p.stop, label: "Cắt lỗ" }] };
}

/** Nến ngày/tuần + KL + vùng SC–AR + mốc Wyckoff. Phân tích luôn theo khung ngày; khung tuần để xem bối cảnh. */
export default function WyckoffChart({ data, analysis, unit, sel, onRange, stats }: {
  data: Ohlcv[]; analysis: Analysis | null; unit: "pt" | "k";
  /** kết quả backtest của loại kế hoạch hiện tại, hiện cạnh kịch bản */
  stats?: PlanStats | null;
  /** khoảng đang phân tích (tô nền); from = to khi chỉ chọn một ngày */
  sel?: { from: string; to: string } | null;
  /** người dùng kéo chọn khoảng [from, to] (ngày giao dịch) trên biểu đồ */
  onRange?: (from: string, to: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [tf, setTf] = useState<Tf>("D");
  const rowsOf = useMemo(() => ({ D: data, W: group(data, KEY.W) }), [data]);
  const [picking, setPicking] = useState(false);              // đang ở chế độ kéo chọn khoảng
  const [drag, setDrag] = useState<{ x0: number; x1: number } | null>(null);
  const [showSc, setShowSc] = useState(true);                 // vẽ kịch bản Wyckoff
  useEffect(() => { try { if (localStorage.getItem(SC_KEY) === "0") setShowSc(false); } catch { /* không có storage */ } }, []);
  const toggleSc = () => {
    setShowSc(!showSc);
    try { localStorage.setItem(SC_KEY, showSc ? "0" : "1"); } catch { /* không có storage */ }
  };
  const sc = useMemo(() => (tf === "D" && unit === "k" && analysis ? scenario(analysis.plan, analysis.c) : null), [tf, unit, analysis]);

  useEffect(() => {
    const rows = rowsOf[tf];
    const k = KEY[tf];                                 // khóa thời gian của mốc sự kiện trên khung đang xem
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
    chartRef.current = chart;
    if (sel) {   // tô nền khoảng đang phân tích (vẽ trước để nằm dưới nến)
      const a = k(sel.from), b = k(sel.to);
      // vùng (area) giá trị 1 trên thang 0–1 riêng: phủ kín từ trên xuống dưới, không bị sọc như cột histogram
      const band = chart.addAreaSeries({
        priceScaleId: "sel", lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
        lineColor: "transparent", topColor: accent + "1a", bottomColor: accent + "1a",
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }),
      });
      chart.priceScale("sel").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
      band.setData(rows.filter((r) => r.d >= a && r.d <= b).map((r) => ({ time: r.d as Time, value: 1 })));
    }
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
      // vùng tích lũy: tô nền SC–AR từ ngày SC tới phiên phân tích, đường trần/đáy đứt nét đậm
      const days = rows.filter((r) => r.d >= k(rg.start) && r.d <= k(analysis.d)).map((r) => r.d as Time);
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
        text: e.k + (e.vx && tf === "D" ?` x${e.vx.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}` : ""),
      }));
    // mốc phân phối (màu đỏ); bỏ AR/ST để không lẫn với mốc tích lũy cùng tên
    (analysis?.distrib?.events ?? [])
      .filter((e) => k(e.d) >= first && ["BC", "UTAD", "SOW", "LPSY"].includes(e.k))
      .forEach((e) => markers.push({
        time: k(e.d) as Time, position: e.pos === "high" ? "aboveBar" : "belowBar",
        color: down, shape: e.pos === "high" ? "arrowDown" : "arrowUp", text: e.k,
      }));
    candles.setMarkers(markers.sort((a, b) => (a.time < b.time ? -1 : 1)));

    // kịch bản: đổi số phiên -> ngày (ngày giao dịch thật nếu có nến sau phiên phân tích, hết thì sinh thứ 2–6)
    const iA = analysis ? rows.findIndex((r) => r.d === analysis.d) : -1;
    let scEnd = -1;                                    // chỉ số logic của điểm cuối kịch bản
    if (sc && showSc && iA >= 0) {
      const extra: string[] = [];
      const dayAt = (n: number) => {
        const i = iA + n;
        if (i < rows.length) return rows[i].d;
        while (extra.length <= i - rows.length) {
          const t = new Date((extra[extra.length - 1] ?? rows[rows.length - 1].d) + "T00:00:00Z");
          do t.setUTCDate(t.getUTCDate() + 1); while (t.getUTCDay() === 0 || t.getUTCDay() === 6);
          extra.push(t.toISOString().slice(0, 10));
        }
        return extra[i - rows.length];
      };
      // nội suy từng phiên giữa các điểm để khoảng cách trên trục thời gian đúng số phiên
      const path = (nodes: Node[]) => nodes.slice(1).flatMap((b, j) => {
        const a = nodes[j];
        return Array.from({ length: b.n - a.n + (j === 0 ? 1 : 0) }, (_, s) => {
          const n = a.n + s + (j === 0 ? 0 : 1);
          return { time: dayAt(n) as Time, value: a.price + (b.price - a.price) * (n - a.n) / (b.n - a.n) };
        });
      });
      const dash = { lineWidth: 2 as const, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
      const dot = (nodes: Node[], color: string): SeriesMarker<Time>[] => nodes.filter((x) => x.label)
        .map((x) => ({ time: dayAt(x.n) as Time, position: "inBar", color, shape: "circle", text: x.label }));
      const green = css("--green") || up;
      const okLine = chart.addLineSeries({ ...dash, color: green });
      okLine.setData(path(sc.ok)); okLine.setMarkers(dot(sc.ok, green));
      const failLine = chart.addLineSeries({ ...dash, color: down });
      failLine.setData(path(sc.fail)); failLine.setMarkers(dot(sc.fail, down));
      scEnd = iA + Math.max(sc.ok[sc.ok.length - 1].n, sc.fail[sc.fail.length - 1].n);
    }

    // đang xem một khoảng/ngày: căn khoảng đó vào giữa, chừa hai bên để thấy trước và sau
    const i0 = sel ? rows.findIndex((r) => r.d >= k(sel.from)) : -1;
    if (sel && i0 >= 0) {
      const i1 = rows.findLastIndex((r) => r.d <= k(sel.to));
      const pad = Math.max(30, Math.round((i1 - i0) * 0.6));
      chart.timeScale().setVisibleLogicalRange({ from: i0 - pad, to: Math.max(i1 + pad, scEnd + 3) });
    } else if (SHOW[tf] && rows.length > SHOW[tf]) {
      // mở sẵn đoạn cuối (ngày ≈1 năm, tuần ≈3 năm), kéo sang trái để xem cũ hơn; chừa chỗ cho kịch bản
      chart.timeScale().setVisibleLogicalRange({ from: rows.length - SHOW[tf], to: Math.max(rows.length + 2, scEnd + 3) });
    } else chart.timeScale().fitContent();
    return () => { chart.remove(); chartRef.current = null; };
  }, [rowsOf, tf, analysis, unit, sel?.from, sel?.to, sc, showSc]);

  // chế độ chọn khoảng: tắt kéo/zoom của biểu đồ để chuột dùng cho việc chọn
  useEffect(() => {
    chartRef.current?.applyOptions({ handleScroll: !picking, handleScale: !picking });
  }, [picking, tf, analysis]);

  /** vị trí x (px trong khung) -> ngày giao dịch; khung tuần: đầu khoảng = phiên đầu tuần, cuối = phiên cuối tuần */
  const xToDay = (x: number, end: boolean) => {
    const rows = rowsOf[tf], lg = chartRef.current?.timeScale().coordinateToLogical(x);
    if (lg == null || !rows.length) return null;
    const w = rows[Math.min(rows.length - 1, Math.max(0, Math.round(lg)))].d;
    if (tf === "D") return w;
    const inWeek = data.filter((r) => KEY.W(r.d) === w);
    return (end ? inWeek[inWeek.length - 1] : inWeek[0])?.d ?? w;
  };
  const relX = (e: PointerEvent) => e.clientX - e.currentTarget.getBoundingClientRect().left;
  const finish = () => {
    if (drag && Math.abs(drag.x1 - drag.x0) > 4) {
      const a = xToDay(Math.min(drag.x0, drag.x1), false), b = xToDay(Math.max(drag.x0, drag.x1), true);
      if (a && b && a < b) { onRange?.(a, b); setPicking(false); }
    }
    setDrag(null);
  };

  return (
    <>
      <div className="row" style={{ marginBottom: 8 }}>
        <div className="tabs">
          {(Object.keys(TF_LABEL) as Tf[]).map((t) => (
            <button key={t} className={tf === t ? "on" : ""} onClick={() => setTf(t)}>{TF_LABEL[t]}</button>
          ))}
        </div>
        {onRange && <button className={`btn${picking ? " primary" : ""}`} onClick={() => { setPicking(!picking); setDrag(null); }}
          title="Kéo chuột qua một đoạn để phân tích Wyckoff trong đoạn đó">
          {picking ? "Kéo chuột chọn khoảng… (bấm để hủy)" : "↔ Chọn khoảng phân tích"}</button>}
        {sc && <button className={`btn${showSc ? " primary" : ""}`} onClick={toggleSc}
          title="Đường đứt nét: xanh = kịch bản thành công tới các mục tiêu, đỏ = kịch bản hỏng về cắt lỗ">
          {showSc ? "✓ Kịch bản" : "Kịch bản"}</button>}
        {tf !== "D" && <span className="muted" style={{ fontSize: 12.5 }}>
          Mốc Wyckoff tính theo ngày, gắn vào {TF_LABEL[tf].toLowerCase()} chứa ngày đó · kéo/cuộn để xem thêm</span>}
      </div>
      <div style={{ position: "relative" }}>
        <div ref={box} style={{ width: "100%", height: 460 }} />
        {picking && (   // lớp phủ nhận thao tác kéo khi đang chọn khoảng
          <div style={{ position: "absolute", inset: 0, zIndex: 10, cursor: "col-resize", touchAction: "none" }}
            onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); const x = relX(e); setDrag({ x0: x, x1: x }); }}
            onPointerMove={(e) => { if (drag) setDrag({ ...drag, x1: relX(e) }); }}
            onPointerUp={finish} onPointerCancel={() => setDrag(null)}>
            {drag && <div style={{
              position: "absolute", top: 0, bottom: 0, left: Math.min(drag.x0, drag.x1), width: Math.abs(drag.x1 - drag.x0),
              background: "var(--accent-soft)", borderLeft: "2px solid var(--accent)", borderRight: "2px solid var(--accent)",
            }} />}
          </div>
        )}
      </div>
      {sc && showSc && <p className="muted" style={{ margin: "6px 0 0", fontSize: 12.5 }}>
        Đường đứt nét: <span className="up">xanh</span> = kịch bản thành công (vào → các mục tiêu Nhân–Quả),{" "}
        <span className="down">đỏ</span> = kịch bản hỏng (về cắt lỗ). Minh họa theo kế hoạch Wyckoff, thời gian ước lượng — không phải dự báo.
        <br />{stats ? <>
          <b>Lịch sử {stats.period}</b> ({num(stats.n)} lệnh {stats.plan}, đã tính phí + trượt giá {num(stats.slip, 2)}%/chiều{stats.n < 30 ? ", ít mẫu" : ""}):{" "}
          chạm T1 <b>{num(stats.hit_t1)}%</b> · cắt lỗ <b>{num(stats.stop)}%</b> · hết thời gian {num(stats.timeout)}% ·
          R TB <b className={stats.avg_r >= 0 ? "up" : "down"}>{num(stats.avg_r, 2)}</b> (KTC95% {num(stats.ci_lo, 2)} … {num(stats.ci_hi, 2)}
          {stats.ci_lo <= 0 && stats.ci_hi >= 0 ? ", chưa chắc có lợi thế" : ""}) · giữ TB {num(stats.avg_days)} phiên
        </> : <>Chưa có thống kê lịch sử cho loại kế hoạch này (chạy <code>app.backtest</code>).</>}
      </p>}
    </>
  );
}
