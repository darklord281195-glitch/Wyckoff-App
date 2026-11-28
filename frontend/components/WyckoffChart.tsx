"use client";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import {
  createChart, ColorType, CrosshairMode, LineStyle, IChartApi, ISeriesApi, SeriesMarker, Time,
} from "lightweight-charts";
import { api, num, pct, fullDate, price as fmtPrice, type Analysis, type Ohlcv, type Plan, type PlanStats } from "@/lib/api";
import { channelWyckoff } from "@/lib/channelWyckoff";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
type Tf = "H" | "D" | "3D" | "W";
const TF_LABEL: Record<Tf, string> = { H: "1 giờ", D: "Ngày", "3D": "3 ngày", W: "Tuần" };
/** tuần chứa ngày d = ngày thứ 2 của tuần */
const weekOf = (d: string) => {
  const t = new Date(d + "T00:00:00Z");
  t.setUTCDate(t.getUTCDate() - (t.getUTCDay() + 6) % 7);
  return t.toISOString().slice(0, 10);
};
/** khóa nến của ngày d trên khung 3 ngày (khối 3 phiên liên tiếp tính từ phiên đầu) hoặc 1 giờ (nến đầu của ngày) */
function keyMap(days: string[], bars: string[]) {
  const m = new Map<string, string>();
  bars.forEach((b) => { if (!m.has(b.slice(0, 10))) m.set(b.slice(0, 10), b); });
  days.forEach((d, i) => { if (!m.has(d)) m.set(d, days[i - (i % 3)]); });
  return (d: string) => m.get(d) ?? d;
}
/** số nến hiện sẵn khi mở khung (1 giờ ≈ 2 tháng, ngày ≈ 1 năm, 3 ngày ≈ 1,5 năm, tuần ≈ 3 năm); kéo/zoom để xem thêm */
const SHOW: Record<Tf, number> = { H: 220, D: 260, "3D": 125, W: 156 };
/** thời gian cho lightweight-charts: ngày giữ chuỗi, nến giờ đổi sang số giây (giờ VN hiển thị như UTC) */
const T = (d: string) => (d.length > 10 ? Date.parse(d + ":00Z") / 1000 : d) as Time;

/** gộp nến ngày thành nến tuần / 3 ngày */
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

/** RSI Wilder chu kỳ n (null ở n nến đầu) */
const rsiW = (cl: number[], n: number) => {
  const out: (number | null)[] = cl.map(() => null);
  let g = 0, l = 0;
  for (let i = 1; i < cl.length; i++) {
    const d = cl[i] - cl[i - 1], up = Math.max(d, 0), dn = Math.max(-d, 0);
    if (i <= n) { g += up / n; l += dn / n; } else { g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n; }
    if (i >= n) out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  return out;
};
/** MCDX Plus (như backend core/mcdx.py): banker = 1,5 × (RSI50 − 50), hot = 0,7 × (RSI40 − 30), kẹp 0–20; TB 10 phiên của banker */
export function mcdx(cl: number[]) {
  const clip = (x: number | null, s: number, b: number) => (x == null ? null : Math.min(20, Math.max(0, s * (x - b))));
  const banker = rsiW(cl, 50).map((x) => clip(x, 1.5, 50)), hot = rsiW(cl, 40).map((x) => clip(x, 0.7, 30));
  const ma = banker.map((_, i) => {
    const w = banker.slice(Math.max(0, i - 9), i + 1);
    return w.length === 10 && w.every((x) => x != null) ? (w as number[]).reduce((a, b) => a + b, 0) / 10 : null;
  });
  return { banker, hot, ma };
}

/** Nhãn trạng thái MCDX, cùng luật với backend core/mcdx.py (state_of / STATES) */
export const MCDX_STATES: Record<string, [string, "good" | "warn" | "bad" | "info", string]> = {
  none: ["Chưa ai kéo", "bad", "Không có đỏ, vàng thấp: xu hướng dài hạn chưa tăng, dòng tiền đầu cơ cũng yếu. Đứng ngoài."],
  spec: ["Chỉ có đầu cơ", "warn", "Có vàng (lướt sóng) nhưng chưa có đỏ: xu hướng dài hạn chưa tăng. Không mua theo, chờ cấu trúc."],
  exit: ["Tay to rút ở vùng cao", "bad", "Đỏ co lại trong khi giá ở gần đỉnh 20 phiên: dấu hiệu phân phối. Siết cắt lỗ, không mua mới."],
  enter: ["Tay to bắt đầu vào", "good", "Đỏ vừa xuất hiện / dâng dần: thường gặp lúc chuyển Pha C sang D. Theo dõi sát, chờ điểm mua của kế hoạch."],
  lead: ["Tay to dẫn dắt", "good", "Đỏ trên nửa cột và còn tăng: đang trong nhịp tăng (Pha D/E). Chỉ mua ở nhịp lùi (LPS/Backup)."],
  fade: ["Tay to giảm", "warn", "Đỏ đang co lại so với 5 phiên trước: đà tăng dài hạn yếu đi."],
  hold: ["Tay to có mặt", "info", "Có đỏ, không tăng không giảm rõ."],
};
export function mcdxState(b: number, b5: number | null, ma: number | null, h: number, cl: number[]) {
  const last20 = cl.slice(-20), nearTop = cl.length >= 20 && cl[cl.length - 1] >= 0.97 * Math.max(...last20);
  const falling = b5 != null && b5 - b >= 2 && (ma == null || b < ma);
  if (b <= 0) return h >= 4 ? "spec" : "none";
  if (falling && nearTop) return "exit";
  if (b5 != null && (b5 <= 0 || (b - b5 >= 2 && b < 10))) return "enter";
  if (b >= 10 && (ma == null || b >= ma)) return "lead";
  if (falling) return "fade";
  return "hold";
}
export const TONE_COLOR = { good: "var(--up)", warn: "var(--warn)", bad: "var(--down)", info: "var(--muted)" } as const;

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
/** k nến tương lai sau nến d: giờ giao dịch (9,10,11,13,14h), ngày thứ 2–6, khối 3 ngày, hoặc tuần */
function futureDays(d: string, k: number, tf: Tf) {
  const out: string[] = [], t = new Date((d.length > 10 ? d : d + "T00:00") + ":00Z");
  let s = 0;
  while (out.length < k) {
    if (tf === "H") t.setUTCHours(t.getUTCHours() + 1);
    else t.setUTCDate(t.getUTCDate() + (tf === "W" ? 7 : 1));
    if (tf !== "W" && (t.getUTCDay() === 0 || t.getUTCDay() === 6)) continue;
    if (tf === "H") { if ([9, 10, 11, 13, 14].includes(t.getUTCHours())) out.push(t.toISOString().slice(0, 16)); }
    else if (tf !== "3D" || ++s % 3 === 0) out.push(t.toISOString().slice(0, 10));
  }
  return out;
}
// Kênh song song do người dùng vẽ: đường chính qua 2 điểm a–b, đường song song lệch dp; lưu theo mã + khung
const CH_KEY = "wyckoff.channels";                          // localStorage
type ChPt = { d: string; x: number; p: number };            // nến d (+ x nến sau nến cuối nếu bấm vào vùng tương lai), giá p
type Channel = { a: ChPt; b: ChPt; dp: number };
const CH_EXT: Record<Tf, number> = { H: 30, D: 30, "3D": 15, W: 12 };   // số nến kéo dài kênh về phía trước
const CH_COLOR = "#0ea5e9";
/** chỉ số nến bắt đầu và giá đường chính tại nến i (null nếu điểm không còn trên khung) */
function chGeom(c: Channel, idx: (q: ChPt) => number | null) {
  const ia = idx(c.a), ib = idx(c.b);
  if (ia == null || ib == null || ia === ib) return null;
  const k = (c.b.p - c.a.p) / (ib - ia);
  const at = (i: number) => c.a.p + k * (i - ia);
  return { i0: Math.min(ia, ib), k, at, lo: (i: number) => Math.min(at(i), at(i) + c.dp), hi: (i: number) => Math.max(at(i), at(i) + c.dp) };
}

const IND_KEY = "wyckoff.indicators";                      // localStorage: bật/tắt RSI/MACD
const MCDX_KEY = "wyckoff.mcdx";                           // localStorage: bật/tắt MCDX

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
export default function WyckoffChart({ sym, data, analysis, unit, sel, onRange, stats }: {
  /** mã: có thì cho xem khung 1 giờ (tải riêng từ VNDirect) */
  sym?: string;
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
  const [hourly, setHourly] = useState<Ohlcv[] | null>(null);
  const [hErr, setHErr] = useState<string | null>(null);
  useEffect(() => { setHourly(null); setHErr(null); }, [sym]);
  useEffect(() => {
    if (tf !== "H" || !sym || hourly) return;
    api<Ohlcv[]>(`/api/symbols/${sym}/hourly`).then(setHourly).catch((e) => setHErr(String(e)));
  }, [tf, sym, hourly]);
  /** nến + khóa ngày -> nến của từng khung */
  const view = useMemo(() => {
    const k3 = keyMap(data.map((r) => r.d), []);
    const H = hourly ?? [];
    return {
      D: { rows: data, k: (d: string) => d },
      "3D": { rows: group(data, k3), k: k3 },
      W: { rows: group(data, weekOf), k: weekOf },
      H: { rows: H, k: keyMap([], H.map((r) => r.d)) },
    } as Record<Tf, { rows: Ohlcv[]; k: (d: string) => string }>;
  }, [data, hourly]);
  const [picking, setPicking] = useState(false);              // đang ở chế độ kéo chọn khoảng
  const [drag, setDrag] = useState<{ x0: number; x1: number } | null>(null);
  const [vtip, setVtip] = useState<{ x: number; y: number; d: string; v: number; vx: number | null; chg: number | null } | null>(null);   // hover cột KL
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
  const box3 = useRef<HTMLDivElement>(null);
  const [showMcdx, setShowMcdx] = useState(false);            // MCDX Plus bên dưới: mặc định tắt
  useEffect(() => { try { if (localStorage.getItem(MCDX_KEY) === "1") setShowMcdx(true); } catch { /* không có storage */ } }, []);
  const toggleMcdx = () => {
    setShowMcdx(!showMcdx);
    try { localStorage.setItem(MCDX_KEY, showMcdx ? "0" : "1"); } catch { /* không có storage */ }
  };
  const [showIchi, setShowIchi] = useState(false);            // mây Ichimoku trên biểu đồ giá: mặc định tắt
  useEffect(() => { try { if (localStorage.getItem(ICHI_KEY) === "1") setShowIchi(true); } catch { /* không có storage */ } }, []);
  const toggleIchi = () => {
    setShowIchi(!showIchi);
    try { localStorage.setItem(ICHI_KEY, showIchi ? "0" : "1"); } catch { /* không có storage */ }
  };
  const sc = useMemo(() => (tf === "D" && unit === "k" && analysis ? scenario(analysis.plan, analysis.c) : null), [tf, unit, analysis]);

  // ---- kênh song song
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const autoMarks = useRef<SeriesMarker<Time>[]>([]);        // mốc Wyckoff tự dò (ẩn khi có kênh để không chồng nhãn)
  const [chartVer, setChartVer] = useState(0);              // tăng mỗi lần biểu đồ được tạo lại -> vẽ lại kênh
  const chKey = `${CH_KEY}.${sym ?? "_"}.${tf}`;
  const [channels, setChannels] = useState<Channel[]>([]);
  useEffect(() => {
    try { setChannels(JSON.parse(localStorage.getItem(chKey) || "[]")); } catch { setChannels([]); }
  }, [chKey]);
  const saveCh = (xs: Channel[]) => {
    setChannels(xs);
    try { localStorage.setItem(chKey, JSON.stringify(xs)); } catch { /* không có storage */ }
  };
  type Q = { i: number; p: number };
  const [drawing, setDrawing] = useState<{ pts: Q[]; m: Q | null } | null>(null);
  useEffect(() => {
    if (!drawing) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawing(null); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [drawing]);
  useEffect(() => setDrawing(null), [tf, sym]);
  const idxOf = (q: ChPt) => { const j = view[tf].rows.findIndex((r) => r.d === q.d); return j < 0 ? null : j + q.x; };
  const toPt = (q: Q): ChPt => {
    const rows = view[tf].rows, j = Math.min(rows.length - 1, q.i);
    return { d: rows[j].d, x: q.i - j, p: q.p };
  };
  /** vị trí chuột -> (chỉ số nến, giá) */
  const pick = (e: PointerEvent): Q | null => {
    const r = e.currentTarget.getBoundingClientRect();
    const lg = chartRef.current?.timeScale().coordinateToLogical(e.clientX - r.left);
    const p = candleRef.current?.coordinateToPrice(e.clientY - r.top);
    return lg == null || p == null ? null : { i: Math.max(0, Math.round(lg)), p };
  };
  const clickDraw = (q: Q) => {
    if (!drawing) return;
    const pts = [...drawing.pts, q];
    if (pts.length === 2 && pts[1].i === pts[0].i) return;          // 2 điểm cùng nến: chưa ra đường
    if (pts.length < 3) return setDrawing({ pts, m: q });
    const [a, b] = pts;
    const base = a.p + (b.p - a.p) / (b.i - a.i) * (q.i - a.i);
    const ch = { a: toPt(a), b: toPt(b), dp: q.p - base };
    saveCh([...channels, ch]);
    setDrawing(null);
  };
  /** nến của khung đang xem -> ngày giao dịch (tuần / 3 ngày: phiên đầu của nến) */
  const dayOf = (w: string) => {
    if (tf === "D" || tf === "H") return w.slice(0, 10);
    return data.find((r) => view[tf].k(r.d) === w)?.d ?? w;
  };
  const analyseCh = (c: Channel) => {
    if (!onRange || !data.length) return;
    const ia = idxOf(c.a), ib = idxOf(c.b), rows = view[tf].rows;
    if (ia == null || ib == null) return;
    const from = dayOf(rows[Math.min(ia, ib, rows.length - 1)].d), to = data[data.length - 1].d.slice(0, 10);
    if (from < to) onRange(from, to);
  };
  useEffect(() => {
    const chart = chartRef.current, rows = view[tf].rows, n = rows.length, muted = css("--muted");
    if (!chart || !n || !channels.length) return;
    const ext = CH_EXT[tf], fut = futureDays(rows[n - 1].d, ext, tf), end = n - 1 + ext;
    const time = (i: number) => T(i < n ? rows[i].d : fut[i - n]);
    const made: ISeriesApi<"Line">[] = [];
    channels.forEach((c) => {
      const g = chGeom(c, idxOf);
      if (!g || g.i0 >= end) return;
      ([[0, 2, LineStyle.Solid], [c.dp, 2, LineStyle.Solid], [c.dp / 2, 1, LineStyle.Dashed]] as const).forEach(([off, w, style]) => {
        const s = chart.addLineSeries({ color: CH_COLOR, lineWidth: w, lineStyle: style, priceLineVisible: false,
          lastValueVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: () => null });
        s.setData([{ time: time(g.i0), value: g.at(g.i0) + off }, { time: time(end), value: g.at(end) + off }]);
        made.push(s);
      });
      // Wyckoff theo kênh: nhãn từng lượt chạm cạnh + dải màu từng pha
      const w = channelWyckoff(rows, g.i0, g.lo, g.hi);
      if (!w) return;
      const hidden = { lineVisible: false, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => null } as const;
      const span = rows.slice(g.i0);
      const lows = chart.addLineSeries(hidden), highs = chart.addLineSeries(hidden);
      lows.setData(span.map((r) => ({ time: T(r.d), value: r.l })));
      highs.setData(span.map((r) => ({ time: T(r.d), value: r.h })));
      const mk = (pos: "low" | "high") => w.events.filter((e) => e.pos === pos).map((e) => ({
        time: T(rows[e.i].d), position: pos === "low" ? "belowBar" : "aboveBar", color: CH_COLOR,
        shape: pos === "low" ? "arrowUp" : "arrowDown",
        text: e.k + (e.vx != null && tf === "D" ? ` x${e.vx.toLocaleString("vi-VN")}` : ""),
      }) as SeriesMarker<Time>);
      const phaseMk = w.phases.map((p) => ({ time: T(rows[p.i0].d), position: "aboveBar", color: muted, shape: "square",
        size: 0.5, text: `Pha ${p.ph}` }) as SeriesMarker<Time>);
      const byTime = (a: SeriesMarker<Time>, b: SeriesMarker<Time>) => String(a.time) < String(b.time) ? -1 : String(a.time) > String(b.time) ? 1 : 0;
      lows.setMarkers(mk("low").sort(byTime));
      highs.setMarkers([...mk("high"), ...phaseMk].sort(byTime));
      made.push(lows, highs);
      candleRef.current?.setMarkers([]);
      w.phases.forEach((p, q) => {
        const col = (p.ph === "Gãy" || p.ph === "Hỏng" ? "#ef4444" : CH_COLOR) + (q % 2 ? "1f" : "10");
        const band = chart.addAreaSeries({ priceScaleId: "chph", lastValueVisible: false, priceLineVisible: false,
          crosshairMarkerVisible: false, lineColor: "transparent", topColor: col, bottomColor: col,
          autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }) });
        chart.priceScale("chph").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
        band.setData(rows.slice(p.i0, p.i1 + 1).map((r) => ({ time: T(r.d), value: 1 })));
        made.push(band as unknown as ISeriesApi<"Line">);
      });
    });
    return () => {
      if (chartRef.current !== chart) return;
      made.forEach((s) => { try { chart.removeSeries(s); } catch { /* đã gỡ */ } });
      candleRef.current?.setMarkers(autoMarks.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartVer, channels]);
  /** nét xem trước khi đang vẽ (px trong khung) */
  const preview = () => {
    const ts = chartRef.current?.timeScale(), cs = candleRef.current;
    if (!drawing || !ts || !cs) return null;
    const P = (q: Q) => ({ x: ts.logicalToCoordinate(q.i as never) ?? 0, y: cs.priceToCoordinate(q.p) ?? 0 });
    const seg = (a: Q, b: Q, key: string, dash = false) => {
      const A = P(a), B = P(b);
      return <line key={key} x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke={CH_COLOR} strokeWidth={2} strokeDasharray={dash ? "5 4" : undefined} />;
    };
    const [a, b] = drawing.pts, m = drawing.m, out = [];
    if (a && !b && m && m.i !== a.i) out.push(seg(a, m, "ab", true));
    if (a && b) {
      out.push(seg(a, b, "ab"));
      if (m) {
        const dp = m.p - (a.p + (b.p - a.p) / (b.i - a.i) * (m.i - a.i));
        out.push(seg({ i: a.i, p: a.p + dp }, { i: b.i, p: b.p + dp }, "cd", true));
      }
    }
    drawing.pts.forEach((q, j) => { const A = P(q); out.push(<circle key={"p" + j} cx={A.x} cy={A.y} r={4} fill={CH_COLOR} />); });
    return out;
  };

  useEffect(() => {
    const { rows, k } = view[tf];                     // k: khóa thời gian của mốc sự kiện trên khung đang xem
    if (!box.current || rows.length === 0) return;
    const muted = css("--muted"), grid = css("--grid"), accent = css("--accent");
    const up = css("--up"), down = css("--down"), surface = css("--surface");
    const chart: IChartApi = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: surface }, textColor: muted, fontFamily: css("--font") },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: grid, scaleMargins: { top: 0.08, bottom: 0.28 }, minimumWidth: 70 },   // = biểu đồ RSI/MACD để trục thời gian thẳng hàng
      timeScale: { borderColor: grid, timeVisible: tf === "H" },
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
      const t = (i: number) => T(i < n ? rows[i].d : fut[i - n]);      // chỉ số nến -> ngày (gồm 26 nến tương lai)
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
      const a = k(sel.from);
      // vùng (area) giá trị 1 trên thang 0–1 riêng: phủ kín từ trên xuống dưới, không bị sọc như cột histogram
      const band = chart.addAreaSeries({
        priceScaleId: "sel", lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
        lineColor: "transparent", topColor: accent + "1a", bottomColor: accent + "1a",
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }),
      });
      chart.priceScale("sel").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
      band.setData(rows.filter((r) => r.d >= a && r.d.slice(0, 10) <= sel.to).map((r) => ({ time: T(r.d), value: 1 })));
    }
    const candles = chart.addCandlestickSeries({
      upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down,
    });
    candles.setData(rows.map((r) => ({ time: T(r.d), open: r.o, high: r.h, low: r.l, close: r.c })));
    candleRef.current = candles;

    const vol = chart.addHistogramSeries({
      priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false,
      priceFormat: { type: "custom", minMove: 0.01, formatter: (v: number) => v.toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " tr" },
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    const evDays = new Set(analysis?.events.map((e) => k(e.d)));
    vol.setData(rows.map((r) => ({
      time: T(r.d), value: r.v,
      color: evDays.has(r.d) ? accent : r.c >= r.o ? up + "66" : down + "66",
    })));
    // đường KL trung bình 20 nến: cột vượt đường = KL trên TB20
    let sum = 0;
    const ma20 = rows.flatMap((r, i) => {
      sum += r.v - (i >= 20 ? rows[i - 20].v : 0);
      return i >= 19 ? [{ time: T(r.d), value: sum / 20 }] : [];
    });
    chart.addLineSeries({
      priceScaleId: "vol", color: "#f59e0b", lineWidth: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    }).setData(ma20);
    // hover vào cột KL: hiện KL phiên đó, so với TB20 và % giá
    const at = new Map(rows.map((r, i) => [String(T(r.d)), i]));
    const avg = new Map(ma20.map((m) => [String(m.time), m.value]));
    chart.subscribeCrosshairMove((p) => {
      const i = p.time != null && p.point ? at.get(String(p.time)) : undefined;
      const top = i != null ? vol.priceToCoordinate(rows[i].v) : null, base = vol.priceToCoordinate(0);
      if (i == null || top == null || base == null || p.point!.y < top - 4 || p.point!.y > base + 2) return setVtip(null);
      const r = rows[i], a = avg.get(String(T(r.d)));
      setVtip({ x: p.point!.x, y: top, d: r.d, v: r.v, vx: a ? r.v / a : null, chg: i > 0 ? (r.c / rows[i - 1].c - 1) * 100 : null });
    });

    if (analysis?.range) {
      const rg = analysis.range;
      // vùng tích lũy: tô nền SC–AR từ ngày SC tới phiên phân tích, đường trần/đáy đứt nét đậm
      const days = rows.filter((r) => r.d >= k(rg.start) && r.d.slice(0, 10) <= analysis.d).map((r) => T(r.d));
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
    const has = new Set(rows.map((r) => r.d));          // chỉ gắn mốc vào nến có trên khung (khung 1 giờ chỉ có ~1 năm)
    const markers: SeriesMarker<Time>[] = (analysis?.events ?? [])
      .filter((e) => has.has(k(e.d)))
      .map((e) => ({
        time: T(k(e.d)),
        position: e.pos === "high" ? "aboveBar" : "belowBar",
        color: e.k === "Đỉnh hạ" ? down : accent, shape: e.pos === "high" ? "arrowDown" : "arrowUp",
        // KL/TB20 là của phiên ngày, chỉ ghi trên khung ngày
        text: e.k + (e.vx && tf === "D" ?` x${e.vx.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}` : ""),
      }));
    // mốc phân phối (màu đỏ); bỏ AR/ST để không lẫn với mốc tích lũy cùng tên
    (analysis?.distrib?.events ?? [])
      .filter((e) => has.has(k(e.d)) && ["BC", "UTAD", "SOW", "LPSY"].includes(e.k))
      .forEach((e) => markers.push({
        time: T(k(e.d)), position: e.pos === "high" ? "aboveBar" : "belowBar",
        color: down, shape: e.pos === "high" ? "arrowDown" : "arrowUp", text: e.k,
      }));
    candles.setMarkers(markers.sort((a, b) => (a.time < b.time ? -1 : 1)));
    autoMarks.current = markers;

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
      const i1 = rows.findLastIndex((r) => r.d.slice(0, 10) <= sel.to);
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
      const pts = (xs: (number | null)[]) => rows.map((r, i) => (xs[i] == null ? { time: T(r.d) } : { time: T(r.d), value: xs[i] as number }));
      const base = { priceLineVisible: false, crosshairMarkerVisible: false, lineWidth: 1 as const };
      const rsi = sub.addLineSeries({ ...base, priceScaleId: "rsi", color: "#8b5cf6", lineWidth: 2, title: "RSI 14",
        priceFormat: { type: "price", precision: 0, minMove: 1 },
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
      rsi.setData(pts(ind.rsi));
      [[70, down], [30, up]].forEach(([p, c]) => rsi.createPriceLine({ price: p as number, color: c as string, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: "" }));
      sub.priceScale("rsi").applyOptions({ scaleMargins: { top: 0.04, bottom: 0.56 } });
      const mfmt = { type: "price" as const, precision: unit === "pt" ? 1 : 2, minMove: 0.01 };
      sub.addHistogramSeries({ ...base, priceScaleId: "macd", lastValueVisible: false, priceFormat: mfmt })
        .setData(rows.map((r, i) => (ind.hist[i] == null ? { time: T(r.d) }
          : { time: T(r.d), value: ind.hist[i] as number, color: (ind.hist[i] as number) >= 0 ? up + "88" : down + "88" })));
      sub.addLineSeries({ ...base, priceScaleId: "macd", color: "#2563eb", title: "MACD", priceFormat: mfmt }).setData(pts(ind.macd));
      sub.addLineSeries({ ...base, priceScaleId: "macd", color: "#f59e0b", title: "Tín hiệu", priceFormat: mfmt }).setData(pts(ind.signal));
      sub.priceScale("macd").applyOptions({ scaleMargins: { top: 0.5, bottom: 0.02 } });
      const ts = sub.timeScale(), r0 = chart.timeScale().getVisibleLogicalRange();
      if (r0) ts.setVisibleLogicalRange(r0);
      chart.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) ts.setVisibleLogicalRange(r); });
    }
    // MCDX Plus: cột chồng 0–20 (xanh = nhỏ lẻ, vàng = hot money, đỏ = banker) + đường TB 10 phiên của banker
    let sub2: IChartApi | null = null;
    if (showMcdx && box3.current) {
      sub2 = createChart(box3.current, {
        autoSize: true,
        layout: { background: { type: ColorType.Solid, color: surface }, textColor: muted, fontFamily: css("--font") },
        grid: { vertLines: { color: grid }, horzLines: { color: grid } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: grid, minimumWidth: 70, scaleMargins: { top: 0.06, bottom: 0.02 } },
        timeScale: { borderColor: grid, visible: false },
        handleScroll: false, handleScale: false,
        localization: { priceFormatter: (p: number) => num(p * 5, 0) + "%" },
      });
      const m = mcdx(rows.map((r) => r.c));
      const range = { autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 20 } }) };
      const hist = (color: string, xs: (number | null)[]) => sub2!.addHistogramSeries({ color, priceLineVisible: false,
        lastValueVisible: false, base: 0, ...range })
        .setData(rows.map((r, i) => (xs[i] == null ? { time: T(r.d) } : { time: T(r.d), value: xs[i] as number })));
      hist("#22c55e", m.banker.map((x) => (x == null ? null : 20)));      // nhỏ lẻ: nền xanh cả cột
      hist("#facc15", m.hot);
      hist("#ef4444", m.banker);
      sub2.addLineSeries({ color: css("--fg"), lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, ...range })
        .setData(rows.map((r, i) => (m.ma[i] == null ? { time: T(r.d) } : { time: T(r.d), value: m.ma[i] as number })));
      const ts = sub2.timeScale(), r0 = chart.timeScale().getVisibleLogicalRange();
      if (r0) ts.setVisibleLogicalRange(r0);
      chart.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) ts.setVisibleLogicalRange(r); });
    }
    setChartVer((v) => v + 1);
    return () => { sub?.remove(); sub2?.remove(); chart.remove(); chartRef.current = null; candleRef.current = null; setTip(null); setVtip(null); };
  }, [view, tf, analysis, unit, sel?.from, sel?.to, sc, showSc, showInd, showIchi, showMcdx]);

  // chế độ chọn khoảng: tắt kéo/zoom của biểu đồ để chuột dùng cho việc chọn
  useEffect(() => {
    chartRef.current?.applyOptions({ handleScroll: !picking, handleScale: !picking });
  }, [picking, tf, analysis]);

  /** vị trí x (px trong khung) -> ngày giao dịch; khung tuần: đầu khoảng = phiên đầu tuần, cuối = phiên cuối tuần */
  const xToDay = (x: number, end: boolean) => {
    const { rows, k } = view[tf], lg = chartRef.current?.timeScale().coordinateToLogical(x);
    if (lg == null || !rows.length) return null;
    const w = rows[Math.min(rows.length - 1, Math.max(0, Math.round(lg)))].d;
    if (tf === "D" || tf === "H") return w.slice(0, 10);
    const inWeek = data.filter((r) => k(r.d) === w);
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
          {(Object.keys(TF_LABEL) as Tf[]).filter((t) => t !== "H" || sym).map((t) => (
            <button key={t} className={tf === t ? "on" : ""} onClick={() => setTf(t)}>{TF_LABEL[t]}</button>
          ))}
        </div>
        {tf === "H" && !hourly && <span className="muted" style={{ fontSize: 12.5 }}>
          {hErr ? `Không tải được nến 1 giờ: ${hErr}` : "Đang tải nến 1 giờ…"}</span>}
        {onRange && <button className={`btn${picking ? " primary" : ""}`} onClick={() => { setPicking(!picking); setDrag(null); setDrawing(null); }}
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
        <button className={`btn${showMcdx ? " primary" : ""}`} onClick={toggleMcdx}
          title="MCDX Plus: đỏ = banker (RSI 50), vàng = hot money (RSI 40), xanh = nhỏ lẻ; đường = TB 10 phiên của banker">
          {showMcdx ? "✓ MCDX" : "MCDX"}</button>
        <button className={`btn${drawing ? " primary" : ""}`} onClick={() => { setDrawing(drawing ? null : { pts: [], m: null }); setPicking(false); }}
          title="Bấm 2 điểm để vẽ đường chính (ví dụ 2 đáy), bấm điểm thứ 3 để đặt đường song song (ví dụ 1 đỉnh). Kênh lưu theo mã và khung thời gian, kéo dài về phía trước.">
          {drawing ? `Bấm điểm ${drawing.pts.length + 1}/3… (Esc để hủy)` : "⫽ Kênh song song"}</button>
        {tf !== "D" && <span className="muted" style={{ fontSize: 12.5 }}>
          Mốc Wyckoff tính theo ngày, gắn vào {tf === "H" ? "nến 9h của ngày đó (nến 1 giờ chỉ có ~1 năm gần nhất)"
            : `nến ${TF_LABEL[tf].toLowerCase()} chứa ngày đó`} · kéo/cuộn để xem thêm</span>}
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
        {vtip && (
          <div className="card" style={{
            position: "absolute", left: vtip.x + 12, top: Math.max(0, vtip.y - 60), zIndex: 5, pointerEvents: "none",
            padding: "6px 10px", margin: 0, fontSize: 12.5, whiteSpace: "nowrap", boxShadow: "0 2px 8px #0002",
          }}>
            <b>{vtip.d.length > 10 ? `${vtip.d.slice(11)} ${fullDate(vtip.d.slice(0, 10))}` : fullDate(vtip.d)}</b>
            {vtip.chg != null && <> · <b className={vtip.chg >= 0 ? "up" : "down"}>{pct(vtip.chg, 2)}</b></>}
            <div>KL <b>{num(vtip.v, 2)}</b>{unit === "pt" ? "" : " triệu cp"}
              {vtip.vx != null && <span className="muted"> · x{num(vtip.vx, 1)} TB20</span>}</div>
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
        {drawing && (   // lớp phủ nhận 3 cú bấm khi vẽ kênh
          <div style={{ position: "absolute", inset: 0, zIndex: 10, cursor: "crosshair", touchAction: "none" }}
            onPointerMove={(e) => { const q = pick(e); if (q) setDrawing({ ...drawing, m: q }); }}
            onPointerDown={(e) => { const q = pick(e); if (q) clickDraw(q); }}>
            <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>{preview()}</svg>
          </div>
        )}
      </div>
      {channels.length > 0 && (() => {
        const rows = view[tf].rows, n = rows.length;
        if (!n) return null;
        const c0 = rows[n - 1].c, P = (x: number) => fmtPrice(x, unit), chg = (x: number) => pct((x / c0 - 1) * 100, 1);
        return <div style={{ display: "grid", gap: 6, marginTop: 6, fontSize: 13 }}>
          {channels.map((c, j) => {
            const g = chGeom(c, idxOf);
            if (!g) return null;
            const v1 = g.at(n - 1), v2 = v1 + c.dp, lo = Math.min(v1, v2), hi = Math.max(v1, v2), h = hi - lo;
            const pos = h > 0 ? (c0 - lo) / h * 100 : 50;
            const slope = v1 ? g.k / v1 * 20 * 100 : 0;
            const stop = lo * 0.97;                                      // cắt lỗ dưới cạnh dưới 3% (tránh rũ bỏ / Spring)
            const up = hi - c0, dn = c0 - stop, rr = dn > 0 ? up / dn : null;
            const span = n - 1 - g.i0;
            const [tone, read] = pos > 100
              ? ["var(--up)", `Đã bứt khỏi cạnh trên. Bứt thật khi đóng cửa trên ${P(hi)} với KL lớn rồi lùi về test cạnh trên mà giữ được (giống LPS/Backup); mục tiêu đo theo độ cao kênh ${P(hi + h)} (${chg(hi + h)}).`]
              : pos < 0
              ? ["var(--down)", `Đã thủng cạnh dưới. Nếu không lấy lại được ${P(lo)} trong vài phiên (Spring thất bại) thì kênh hỏng; mục tiêu giảm đo theo độ cao kênh ${P(lo - h)} (${chg(lo - h)}).`]
              : pos <= 25
              ? ["var(--up)", `Giá sát cạnh dưới: vùng mua theo kênh, cắt lỗ ${P(stop)} (${chg(stop)}, dưới cạnh dưới 3% để chừa chỗ cho Spring). Cần thấy KL cạn khi chạm cạnh dưới hoặc một phiên rũ bỏ (Spring) rồi bật lại.`]
              : pos >= 75
              ? ["var(--warn)", `Giá sát cạnh trên: lời/lỗ kém nếu mua lúc này. Chờ bứt cạnh trên có KL (SOS) rồi mua nhịp lùi, hoặc chờ về lại gần cạnh dưới.`]
              : ["var(--muted)", `Giá ở giữa kênh: chưa phải điểm mua đẹp, chờ về gần cạnh dưới hoặc bứt cạnh trên.`];
            return <div key={j} style={{ border: `1px solid ${CH_COLOR}`, borderRadius: 8, padding: "6px 10px" }}>
              <div className="row" style={{ gap: 6, justifyContent: "space-between" }}>
                <span><b style={{ color: CH_COLOR }}>Kênh {j + 1}</b> · {span} nến · dưới {P(lo)} · trên {P(hi)} ·{" "}
                  {pos > 100 ? <b className="up">giá đã vượt cạnh trên</b> : pos < 0 ? <b className="down">giá đã thủng cạnh dưới</b>
                    : <>giá ở <b>{num(pos, 0)}%</b> kênh</>}
                  {" "}· dốc {pct(slope, 1)}/20 nến</span>
                <span className="row" style={{ gap: 4 }}>
                  {onRange && <button className="btn" style={{ fontSize: 12, padding: "2px 8px" }} onClick={() => analyseCh(c)}
                    title="Phân tích Wyckoff chỉ trong khoảng từ điểm đầu của kênh tới phiên mới nhất">Phân tích Wyckoff khoảng này</button>}
                  <button onClick={() => saveCh(channels.filter((_, x) => x !== j))} aria-label={`Xóa kênh ${j + 1}`} title="Xóa kênh"
                    style={{ border: 0, background: "none", cursor: "pointer", color: "var(--muted)", padding: "0 4px" }}>✕</button>
                </span>
              </div>
              <div>
                <b>Tiềm năng:</b> lên cạnh trên <b className="up">{chg(hi)}</b> · về cạnh dưới <b className="down">{chg(lo)}</b>
                {rr != null && up > 0 && <> · lời/lỗ nếu mua {P(c0)}, cắt lỗ {P(stop)} <b className={rr >= 2 ? "up" : rr < 1 ? "down" : undefined}>{num(rr, 1)}</b></>}
                {" "}· bứt cạnh trên: mục tiêu {P(hi + h)} ({chg(hi + h)})
              </div>
              <div style={{ color: tone }}>{read}</div>
              {(() => {
                const w = channelWyckoff(rows, g.i0, g.lo, g.hi);
                if (!w) return null;
                const col = { good: "var(--up)", warn: "var(--warn)", bad: "var(--down)", info: "var(--fg)" }[w.tone];
                return <div style={{ marginTop: 4, paddingTop: 4, borderTop: "1px dashed var(--border, #ddd)" }}>
                  <b>Wyckoff theo kênh:</b> {w.title} · đang ở <b style={{ color: col }}>{w.now.length === 1 ? "Pha " + w.now : w.now}</b>
                  {" "}<span className="muted">({w.phases.map((p) => `${p.ph.length === 1 ? "Pha " + p.ph : p.ph} từ ${fullDate(rows[p.i0].d.slice(0, 10))}`).join(" · ")})</span>
                  <div style={{ color: col }}>{w.advice}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {w.events.map((e) => `${e.k} ${fullDate(rows[e.i].d.slice(0, 10))}${e.vx != null ? ` (KL x${num(e.vx, 1)})` : ""}`).join(" → ")}
                  </div>
                </div>;
              })()}
            </div>;
          })}
          {channels.length > 1 && <div><button className="btn" style={{ fontSize: 12 }} onClick={() => saveCh([])}>Xóa hết kênh</button></div>}
          <div className="muted" style={{ fontSize: 12 }}>Nhãn Wyckoff theo kênh: mỗi lần giá chạm / xuyên cạnh kênh được gắn nhãn
            (mở đầu ở cạnh dưới = tích lũy: SC, AR, ST, Spring, Test, UT, SOS, LPS; ở cạnh trên = phân phối: BC, AR, ST, UTAD, SOW, LPSY),
            xNN = KL so với TB 20 phiên. Luật đơn giản hóa, chưa backtest: dùng để đọc nhanh, không phải tín hiệu mua.
            Mục tiêu bứt = cạnh trên + độ cao kênh. Kế hoạch giao dịch: bấm &quot;Phân tích Wyckoff khoảng này&quot;.</div>
        </div>;
      })()}
      {showInd && <div ref={box2} style={{ width: "100%", height: 220, marginTop: 4 }} />}
      {showMcdx && <McdxPanel box={box3} closes={view[tf].rows.map((r) => r.c)} />}
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

/** Khung MCDX Plus dưới biểu đồ giá + chú giải phiên cuối (%): banker / hot money / nhỏ lẻ, banker so với TB 10 phiên. */
function McdxPanel({ box, closes }: { box: React.RefObject<HTMLDivElement | null>; closes: number[] }) {
  const m = useMemo(() => mcdx(closes), [closes]);
  const i = closes.length - 1, b = m.banker[i], h = m.hot[i], ma = m.ma[i];
  const pctOf = (x: number) => num(x * 5, 0) + "%";
  const st = b != null && h != null ? MCDX_STATES[mcdxState(b, i >= 5 ? m.banker[i - 5] : null, ma, h, closes)] : null;
  return (
    <>
      <div ref={box} style={{ width: "100%", height: 150, marginTop: 4 }} />
      {st && <p style={{ margin: "6px 0 0" }}>
        <span className="pill" style={{ background: "transparent", border: `1px solid ${TONE_COLOR[st[1]]}`, color: TONE_COLOR[st[1]] }}>
          {st[0]}</span> <span style={{ fontSize: 13.5 }}>{st[2]}</span></p>}
      <p className="muted" style={{ margin: "4px 0 0", fontSize: 12.5 }}>
        <b>MCDX Plus</b>{b != null && h != null && <> · phiên cuối:{" "}
          <span style={{ color: "#ef4444", fontWeight: 600 }}>banker {pctOf(b)}</span> ·{" "}
          <span style={{ color: "#ca8a04", fontWeight: 600 }}>hot money {pctOf(Math.max(h - b, 0))}</span> ·{" "}
          <span style={{ color: "#16a34a", fontWeight: 600 }}>nhỏ lẻ {pctOf(20 - Math.max(b, h))}</span>
          {ma != null && <> · banker {b >= ma ? "trên" : "dưới"} đường TB 10 phiên ({b >= ma ? "đang tăng" : "đang giảm"})</>}</>}.
        {" "}Đỏ dâng dần ở vùng đáy = tay to gom; đỏ chiếm trên nửa cột = xu hướng do tay to dẫn; đỏ co lại khi giá ở đỉnh = đang xả.
        Thực chất là RSI 50/40 phiên tách tầng, không phải dữ liệu lệnh thật.
      </p>
    </>
  );
}
