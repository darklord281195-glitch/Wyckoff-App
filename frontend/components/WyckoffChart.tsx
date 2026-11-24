"use client";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import {
  createChart, ColorType, CrosshairMode, LineStyle, IChartApi, SeriesMarker, Time,
} from "lightweight-charts";
import { num, pct, fullDate, price as fmtPrice, type Analysis, type Ohlcv, type Plan, type PlanStats } from "@/lib/api";

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

/** EMA theo chuỗi; trả về cùng độ dài, phần tử đầu = giá trị đầu */
const ema = (xs: number[], n: number) => {
  const a = 2 / (n + 1), out: number[] = [];
  xs.forEach((x, i) => out.push(i ? out[i - 1] + a * (x - out[i - 1]) : x));
  return out;
};
/** RSI(14) kiểu Wilder và MACD(12,26,9); null ở các nến chưa đủ dữ liệu */
export function indicators(cl: number[]) {
  const rsi: (number | null)[] = cl.map(() => null);
  let g = 0, l = 0;
  for (let i = 1; i < cl.length; i++) {
    const d = cl[i] - cl[i - 1], up = Math.max(d, 0), dn = Math.max(-d, 0);
    if (i <= 14) { g += up / 14; l += dn / 14; } else { g = (g * 13 + up) / 14; l = (l * 13 + dn) / 14; }
    if (i >= 14) rsi[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  const e12 = ema(cl, 12), e26 = ema(cl, 26);
  const macd = cl.map((_, i) => e12[i] - e26[i]), sig = ema(macd, 9);
  const ok = (i: number) => i >= 33;          // 26 + 9 − 2 nến để MACD/tín hiệu ổn định
  return {
    rsi, macd: macd.map((m, i) => (ok(i) ? m : null)),
    signal: sig.map((s, i) => (ok(i) ? s : null)), hist: macd.map((m, i) => (ok(i) ? m - sig[i] : null)),
  };
}

type Node = { n: number; price: number; label?: string };   // n = số phiên tính từ phiên phân tích
const SC_KEY = "wyckoff.scenario";                          // localStorage: bật/tắt kịch bản
const ICHI_KEY = "wyckoff.ichimoku";                        // localStorage: bật/tắt mây Ichimoku
const ICHI_SHIFT = 26;
/** Ichimoku 9-26-52: Senkou A/B dời tới trước 26 nến (chỉ số có thể ≥ số nến), Chikou lùi 26 nến */
export function ichimoku(rows: Ohlcv[]) {
  const n = rows.length, mid = (i: number, p: number) => {
    if (i < p - 1) return null;
    let h = -Infinity, l = Infinity;
    for (let j = i - p + 1; j <= i; j++) { h = Math.max(h, rows[j].h); l = Math.min(l, rows[j].l); }
    return (h + l) / 2;
  };
  const tenkan = rows.map((_, i) => mid(i, 9)), kijun = rows.map((_, i) => mid(i, 26));
  const spanA: (number | null)[] = Array(n + ICHI_SHIFT).fill(null), spanB = [...spanA];
  for (let i = 0; i < n; i++) {
    const a = tenkan[i], b = kijun[i];
    spanA[i + ICHI_SHIFT] = a != null && b != null ? (a + b) / 2 : null;
    spanB[i + ICHI_SHIFT] = mid(i, 52);
  }
  const chikou = rows.map((_, i) => (i + ICHI_SHIFT < n ? rows[i + ICHI_SHIFT].c : null));
  return { tenkan, kijun, spanA, spanB, chikou };
}
/** k ngày giao dịch (thứ 2–6) hoặc k tuần sau ngày d */
function futureDays(d: string, k: number, tf: Tf) {
  const out: string[] = [], t = new Date(d + "T00:00:00Z");
  while (out.length < k) {
    t.setUTCDate(t.getUTCDate() + (tf === "W" ? 7 : 1));
    if (tf === "W" || (t.getUTCDay() !== 0 && t.getUTCDay() !== 6)) out.push(t.toISOString().slice(0, 10));
  }
  return out;
}
const IND_KEY = "wyckoff.indicators";                      // localStorage: bật/tắt RSI/MACD

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

const PULLBACK = 0.4;      // mỗi nhịp điều chỉnh ít nhất ~40% nhịp tăng trước đó (Backup/LPS điển hình)
const WAVE_DAYS = 7;       // ~1 nhịp lên–điều chỉnh mỗi 7 phiên (1–4 nhịp mỗi đoạn)
const MIN_SWING = 1.2;     // nhịp tăng tối thiểu ~1,2 ATR: đoạn đi ngang (T1 ≈ T2) vẫn dao động như giá thật

/** Chèn các nhịp lên–điều chỉnh vào từng đoạn đi lên của lộ trình (từ điểm Vào trở đi), vẫn đi qua đúng mọi mốc.
 *  Minh họa hình dạng giá thường gặp, không phải dự báo từng nhịp. */
function zigzag(nodes: Node[], atr: number): Node[] {
  const out: Node[] = [nodes[0]];
  nodes.slice(1).forEach((b, j) => {
    const a = nodes[j], rise = b.price - a.price, len = b.n - a.n;
    // đoạn đầu (giá hiện tại -> điểm Vào) và đoạn đi xuống giữ thẳng; đoạn đi lên chia nhịp theo thời gian
    const waves = j === 0 || rise < 0 || !(atr > 0) ? 1 : Math.max(1, Math.min(4, Math.round(len / WAVE_DAYS)));
    const gain = rise / waves, dur = len / waves;
    const impulse = Math.max(gain / (1 - PULLBACK), MIN_SWING * atr);   // nhịp lên; điều chỉnh = impulse − gain
    for (let w = 0; w < waves - 1; w++) {
      const base = a.price + gain * w, t0 = a.n + dur * w;
      out.push({ n: Math.round(t0 + dur * 0.6), price: base + impulse });   // đỉnh nhịp
      out.push({ n: Math.round(t0 + dur), price: base + gain });            // đáy điều chỉnh (cao dần đều)
    }
    out.push(b);
  });
  return out.filter((x, i, arr) => i === 0 || x.n > arr[i - 1].n);                 // bỏ điểm trùng phiên
}

/** ATR 14 và độ lệch chuẩn lợi nhuận ngày (60 phiên) tính tới phiên i. */
function volatility(rows: Ohlcv[], i: number) {
  const tr = [], lr = [];
  for (let k = Math.max(1, i - 59); k <= i; k++) {
    const p = rows[k - 1].c, b = rows[k];
    tr.push(Math.max(b.h - b.l, Math.abs(b.h - p), Math.abs(b.l - p)));
    if (p > 0 && b.c > 0) lr.push(Math.log(b.c / p));
  }
  const atr = tr.slice(-14).reduce((s, x) => s + x, 0) / Math.max(1, Math.min(14, tr.length));
  const mu = lr.reduce((s, x) => s + x, 0) / Math.max(1, lr.length);
  const sd = Math.sqrt(lr.reduce((s, x) => s + (x - mu) ** 2, 0) / Math.max(1, lr.length - 1));
  return { atr, sd };
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
  const [tip, setTip] = useState<{ x: number; y: number; label: string; price: number } | null>(null);   // hover điểm kịch bản
  const [showSc, setShowSc] = useState(true);                 // vẽ kịch bản Wyckoff
  useEffect(() => { try { if (localStorage.getItem(SC_KEY) === "0") setShowSc(false); } catch { /* không có storage */ } }, []);
  const toggleSc = () => {
    setShowSc(!showSc);
    try { localStorage.setItem(SC_KEY, showSc ? "0" : "1"); } catch { /* không có storage */ }
  };
  const box2 = useRef<HTMLDivElement>(null);
  const [showInd, setShowInd] = useState(false);              // RSI + MACD bên dưới: mặc định tắt
  useEffect(() => { try { if (localStorage.getItem(IND_KEY) === "1") setShowInd(true); } catch { /* không có storage */ } }, []);
  const toggleInd = () => {
    setShowInd(!showInd);
    try { localStorage.setItem(IND_KEY, showInd ? "0" : "1"); } catch { /* không có storage */ }
  };
  const [showIchi, setShowIchi] = useState(false);            // mây Ichimoku trên biểu đồ giá: mặc định tắt
  useEffect(() => { try { if (localStorage.getItem(ICHI_KEY) === "1") setShowIchi(true); } catch { /* không có storage */ } }, []);
  const toggleIchi = () => {
    setShowIchi(!showIchi);
    try { localStorage.setItem(ICHI_KEY, showIchi ? "0" : "1"); } catch { /* không có storage */ }
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
      rightPriceScale: { borderColor: grid, scaleMargins: { top: 0.08, bottom: 0.28 }, minimumWidth: 70 },   // = biểu đồ RSI/MACD để trục thời gian thẳng hàng
      timeScale: { borderColor: grid },
      localization: {
        locale: "vi-VN",
        priceFormatter: (p: number) => unit === "pt"
          ? p.toLocaleString("vi-VN", { maximumFractionDigits: 2 })
          : Math.round(p * 1000).toLocaleString("vi-VN"),
      },
    });
    chartRef.current = chart;
    if (showIchi) {   // vẽ đầu tiên để nến, KL, vùng chọn nằm trên mây
      const ic = ichimoku(rows), n = rows.length;
      const fut = futureDays(rows[n - 1].d, ICHI_SHIFT, tf);
      const t = (i: number) => (i < n ? rows[i].d : fut[i - n]) as Time;      // chỉ số nến -> ngày (gồm 26 nến tương lai)
      const base = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
      // mây = vùng tô từ max(A,B) xuống, rồi vùng màu nền từ min(A,B) xuống che phần dưới
      // shortcut: mặt nạ màu nền che lưới dọc phía dưới mây; lightweight-charts 4 không có kiểu tô giữa hai đường
      const hiA: { time: Time; value: number; topColor: string; bottomColor: string; lineColor: string }[] = [];
      const loA: { time: Time; value: number }[] = [];
      ic.spanA.forEach((a, i) => {
        const b = ic.spanB[i];
        if (a == null || b == null) return;
        const col = a >= b ? up + "33" : down + "33";
        hiA.push({ time: t(i), value: Math.max(a, b), topColor: col, bottomColor: col, lineColor: "transparent" });
        loA.push({ time: t(i), value: Math.min(a, b) });
      });
      chart.addAreaSeries({ ...base, lineWidth: 1 }).setData(hiA);
      chart.addAreaSeries({ ...base, lineColor: "transparent", topColor: surface, bottomColor: surface }).setData(loA);
      const line = (xs: (number | null)[], color: string, title: string) => chart.addLineSeries({ ...base, color, lineWidth: 1, title })
        .setData(xs.flatMap((v, i) => (v == null ? [] : [{ time: t(i), value: v }])));
      line(ic.spanA, up + "aa", "");
      line(ic.spanB, down + "aa", "");
      line(ic.tenkan, "#2563eb", "Tenkan 9");
      line(ic.kijun, "#be185d", "Kijun 26");
      line(ic.chikou, "#94a3b8", "Chikou");
    }
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
        color: e.k === "Đỉnh hạ" ? down : accent, shape: e.pos === "high" ? "arrowDown" : "arrowUp",
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
      const vol = volatility(rows, iA);
      const okPath = path(zigzag(sc.ok, vol.atr));
      // dải biến động ~68%: lộ trình × e^(±σ·√n), σ = độ lệch chuẩn lợi nhuận ngày 60 phiên qua
      const band = (sign: number) => okPath.map((p, n) => ({ time: p.time, value: p.value * Math.exp(sign * vol.sd * Math.sqrt(n)) }));
      const faint = { lineWidth: 1 as const, lineStyle: LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, color: green + "80" };
      if (vol.sd > 0) { chart.addLineSeries(faint).setData(band(1)); chart.addLineSeries(faint).setData(band(-1)); }
      const okLine = chart.addLineSeries({ ...dash, color: green });
      okLine.setData(okPath); okLine.setMarkers(dot(sc.ok, green));
      const failLine = chart.addLineSeries({ ...dash, color: down });
      failLine.setData(path(sc.fail)); failLine.setMarkers(dot(sc.fail, down));
      // hover vào điểm Vào/T1/T2/T3/Cắt lỗ: % lời/lỗ nếu mua ở giá đóng cửa phiên phân tích
      const tips = new Map<string, { label: string; price: number }>();
      [...sc.ok, ...sc.fail].filter((x) => x.label).forEach((x) => tips.set(dayAt(x.n), { label: x.label!, price: x.price }));
      chart.subscribeCrosshairMove((p) => {
        const hit = p.time && p.point ? tips.get(p.time as string) : undefined;
        const y = hit ? okLine.priceToCoordinate(hit.price) : null;
        setTip(hit && p.point && y != null ? { x: p.point.x, y, label: hit.label, price: hit.price } : null);
      });
      scEnd = iA + Math.max(sc.ok[sc.ok.length - 1].n, sc.fail[sc.fail.length - 1].n);
    }
    if (showIchi) scEnd = Math.max(scEnd, rows.length - 1 + ICHI_SHIFT);   // thấy phần mây phía trước

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

    // RSI + MACD: biểu đồ phụ bên dưới, cùng trục thời gian (mỗi nến đều có điểm, null = khoảng trắng để chỉ số logic khớp)
    let sub: IChartApi | null = null;
    if (showInd && box2.current) {
      sub = createChart(box2.current, {
        autoSize: true,
        layout: { background: { type: ColorType.Solid, color: surface }, textColor: muted, fontFamily: css("--font") },
        grid: { vertLines: { color: grid }, horzLines: { color: grid } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: grid, minimumWidth: 70 },
        timeScale: { borderColor: grid, visible: false },
        handleScroll: false, handleScale: false,
      });
      const ind = indicators(rows.map((r) => r.c));
      const pts = (xs: (number | null)[]) => rows.map((r, i) => (xs[i] == null ? { time: r.d as Time } : { time: r.d as Time, value: xs[i] as number }));
      const base = { priceLineVisible: false, crosshairMarkerVisible: false, lineWidth: 1 as const };
      const rsi = sub.addLineSeries({ ...base, priceScaleId: "rsi", color: "#8b5cf6", lineWidth: 2, title: "RSI 14",
        priceFormat: { type: "price", precision: 0, minMove: 1 },
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
      rsi.setData(pts(ind.rsi));
      [[70, down], [30, up]].forEach(([p, c]) => rsi.createPriceLine({ price: p as number, color: c as string, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: "" }));
      sub.priceScale("rsi").applyOptions({ scaleMargins: { top: 0.04, bottom: 0.56 } });
      const mfmt = { type: "price" as const, precision: unit === "pt" ? 1 : 2, minMove: 0.01 };
      sub.addHistogramSeries({ ...base, priceScaleId: "macd", lastValueVisible: false, priceFormat: mfmt })
        .setData(rows.map((r, i) => (ind.hist[i] == null ? { time: r.d as Time }
          : { time: r.d as Time, value: ind.hist[i] as number, color: (ind.hist[i] as number) >= 0 ? up + "88" : down + "88" })));
      sub.addLineSeries({ ...base, priceScaleId: "macd", color: "#2563eb", title: "MACD", priceFormat: mfmt }).setData(pts(ind.macd));
      sub.addLineSeries({ ...base, priceScaleId: "macd", color: "#f59e0b", title: "Tín hiệu", priceFormat: mfmt }).setData(pts(ind.signal));
      sub.priceScale("macd").applyOptions({ scaleMargins: { top: 0.5, bottom: 0.02 } });
      const ts = sub.timeScale(), r0 = chart.timeScale().getVisibleLogicalRange();
      if (r0) ts.setVisibleLogicalRange(r0);
      chart.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) ts.setVisibleLogicalRange(r); });
    }
    return () => { sub?.remove(); chart.remove(); chartRef.current = null; setTip(null); };
  }, [rowsOf, tf, analysis, unit, sel?.from, sel?.to, sc, showSc, showInd, showIchi]);

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
        <button className={`btn${showIchi ? " primary" : ""}`} onClick={toggleIchi}
          title="Ichimoku 9-26-52: mây xanh/đỏ (Senkou A/B, dời trước 26 nến), Tenkan xanh dương, Kijun hồng, Chikou xám">
          {showIchi ? "✓ Ichimoku" : "Ichimoku"}</button>
        <button className={`btn${showInd ? " primary" : ""}`} onClick={toggleInd}
          title="RSI 14 (tím, vạch 70/30) và MACD 12-26-9 (xanh = MACD, cam = tín hiệu, cột = chênh lệch)">
          {showInd ? "✓ RSI/MACD" : "RSI/MACD"}</button>
        {tf !== "D" && <span className="muted" style={{ fontSize: 12.5 }}>
          Mốc Wyckoff tính theo ngày, gắn vào {TF_LABEL[tf].toLowerCase()} chứa ngày đó · kéo/cuộn để xem thêm</span>}
      </div>
      <div style={{ position: "relative" }}>
        <div ref={box} style={{ width: "100%", height: 460 }} />
        {tip && analysis && (
          <div className="card" style={{
            position: "absolute", left: tip.x + 12, top: Math.max(0, tip.y - 52), zIndex: 5, pointerEvents: "none",
            padding: "6px 10px", margin: 0, fontSize: 12.5, whiteSpace: "nowrap", boxShadow: "0 2px 8px #0002",
          }}>
            <b>{tip.label}</b> {fmtPrice(tip.price, unit)}{" "}
            <b className={tip.price >= analysis.c ? "up" : "down"}>{pct((tip.price / analysis.c - 1) * 100, 1)}</b>
            <div className="muted">nếu mua ở {fmtPrice(analysis.c, unit)} (đóng cửa {fullDate(analysis.d)})</div>
          </div>
        )}
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
      {showInd && <div ref={box2} style={{ width: "100%", height: 220, marginTop: 4 }} />}
      {sc && showSc && <p className="muted" style={{ margin: "6px 0 0", fontSize: 12.5 }}>
        Đường đứt nét: <span className="up">xanh</span> = kịch bản thành công (vào → các mục tiêu Nhân–Quả, đi theo nhịp lên –
        điều chỉnh ~40%, độ lớn nhịp theo ATR 14 của mã), <span className="down">đỏ</span> = kịch bản hỏng (về cắt lỗ).
        Hai đường chấm mờ = khoảng giá thường dao động (~68%) nếu mã biến động như 60 phiên qua.
        Hình dạng và thời gian chỉ là minh họa — không phải dự báo từng nhịp.
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
