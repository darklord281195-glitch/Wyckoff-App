export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Levels = { support: number; resistance: number; invalid: number };
export type WEvent = { d: string; k: string; pos: "low" | "high"; price: number; v: number; vx: number | null };
export type Target = { k: string; price: number; basis: string; pct?: number; rr?: number; ce: boolean };
export type Plan = {
  kind: string | null; entry_lo: number | null; entry_hi: number | null; trigger: string;
  stop: number | null; stop_reason: string; time_stop: number; targets: Target[];
  rr: number | null; rr_t1?: number | null; main_target?: string; risk_pct: number | null; in_zone?: boolean;
  ready: { score: number; parts: Record<string, number>; dry?: number; pos?: number };
  cause?: { cols: number; box: number; width: number; conservative: number; aggressive: number };
  notes: string[]; exit: string;
};
export type Analysis = {
  plan?: Plan | null; supply?: boolean;
  d: string; c: number; chg: number; v: number; vx: number | null; ma20: number; ma50: number; ma200: number | null;
  liq: number; pos52: number; rs5?: number | null; rs20?: number | null; rs60?: number | null;
  tag: string; stage: string; extra?: string; weak_drop?: boolean; drop?: number; dist?: number;
  range: { start: string; sup: number; res: number; sc_d: string; ar_d: string } | null;
  sos?: { d: string; v: number; vx: number | null } | null;
  events: WEvent[]; levels: Levels | Record<string, never>;
  /** vùng phân phối gần nhất (BC–AR) và các mốc BC/AR/ST/UTAD/SOW/LPSY; null nếu không có */
  distrib?: { tag: string; top: number; bot: number; start: string; events: WEvent[] } | null;
  /** biến thể sơ đồ mã đang giống: acc1/acc2/dist1/dist2, "acc" = tích lũy chưa rõ mẫu */
  schema?: { variant: string | null; phase: string | null; title: string; note: string };
};
export type Row = {
  sym: string; groups: string[]; floor: string | null; name: string | null; tag: string; stage: string; c: number; chg: number; liq: number;
  rs5: number | null; rs20: number | null; rs60: number | null; dist: number | null; extra: string;
  weak_drop: boolean; levels: Levels; pos52: number;
  ready: number | null; rr: number | null; plan_kind: string | null;
  entry_lo: number | null; entry_hi: number | null; stop: number | null; in_zone: boolean | null;
  fx10: number | null;   // khối ngoại mua ròng 10 phiên, tỷ đồng
};
export type Market = { date: string; light: "green" | "yellow" | "red" | "?"; text: string; c: number; chg: number; tag: string };
export type Signal = { date: string; sym: string; kind: string; is_new: number; text: string };
export type Ohlcv = { d: string; o: number; h: number; l: number; c: number; v: number };
/** Lệnh đang giữ; các trường sau `note` do backend tính theo luật bán (positions.simulate). */
export type Position = {
  id: number; sym: string; kind: string | null; entry_d: string; entry_px: number; qty: number | null;
  stop: number; targets: number[]; note: string | null; sold: number;   // sold: số cp đã bán (bảng sales)
  c?: number; d?: string; days?: number; pnl?: number; cur_stop?: number; left?: number; hit?: number;
  next?: number | null; pending?: string | null; sold_out?: string | null;   // ngày luật đã bán hết
  events?: { d: string; kind: string; text: string }[];
};
/** Một lần bán; pnl % và pnl_vnd đã trừ phí mua 0,15%, bán 0,25%. */
export type Sale = { id: number | null; d: string; px: number; qty: number | null; pos_id: number; sym: string;
  entry_d: string; entry_px: number; pnl: number; pnl_vnd: number | null };
/** Khối ngoại một phiên; buy/sell/net theo tỷ đồng, room = số cp nước ngoài còn được mua. */
export type Foreign = { d: string; buy: number; sell: number; net: number; net_vol: number | null;
  room: number | null; total_room: number | null };
/** Kết quả backtest của một loại kế hoạch (app.backtest); hit_t1/stop/timeout là %. */
export type PlanStats = { plan: string; n: number; hit_t1: number; stop: number; timeout: number; avg_r: number;
  ci_lo: number; ci_hi: number; avg_days: number; period: string; slip: number; updated: string };
/** Cài đặt vốn và ngưỡng rủi ro (backend /api/settings). capital: triệu đồng; còn lại là %. */
export type Settings = { capital: number; risk_pct: number; max_heat: number; max_pos: number; max_sector: number };
/** Rủi ro danh mục (/api/portfolio/risk); tiền tính bằng đồng, heat = % vốn. */
export type PortfolioRisk = {
  capital: number; heat: number; max_heat: number; total_risk: number; total_value: number; n: number; max_pos: number;
  items: { id: number; sym: string; held: number; risk: number; risk_pct: number; value: number; sector: string; below_stop: boolean }[];
  sectors: { name: string; value: number; pct: number }[]; no_qty: string[];
  light: string | null; factor: number; warnings: string[];
};
/** Nhật ký (/api/journal): R thật vs R theo luật, cờ vi phạm. */
export type JournalItem = { id: number; sym: string; kind: string | null; entry_d: string; entry_px: number; stop0: number;
  qty: number | null; status: string; last_sale: string | null; r_real: number | null; r_rule: number | null;
  diff: number | null; rule_done: boolean; flags: string[] };
export type Journal = { items: JournalItem[]; summary: { n: number; open: number; win: number | null; avg_real: number | null;
  avg_rule: number | null; backtest_avg_r: number | null; n_flagged: number; r_lost: number; flag_counts: Record<string, number> } };
/** Sức mạnh một ngành ICB tại phiên quét (/api/sectors). */
export type SectorRow = { icb: string; name: string; n: number; rs20: number | null; rs60: number | null;
  pct_d: number; fx10: number | null };
export type SymbolData = {
  sym: string; groups: string[]; name: string | null; floor: string | null; sector: string | null; unit: "pt" | "k"; ohlcv: Ohlcv[]; analysis: Analysis | null;
  signals: Signal[]; in_watchlist: boolean;
  at: string | null;   // ngày đang xem (null = phiên mới nhất)
  start: string | null; // đầu khoảng phân tích tự chọn (null = dò mặc định 190 phiên)
  foreign: Foreign[]; foreign_error: string | null;
  plan_stats: PlanStats | null;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

/* ---- định dạng kiểu Việt Nam ---- */
const nf = (d: number) => new Intl.NumberFormat("vi-VN", { minimumFractionDigits: d, maximumFractionDigits: d });
export const num = (x: number | null | undefined, d = 0) => (x == null ? "–" : nf(d).format(x));
/** giá nghìn đồng -> đồng (12.65 -> 12.650); chỉ số giữ 2 số lẻ */
export const price = (x: number | null | undefined, unit: "pt" | "k" = "k") =>
  x == null ? "–" : unit === "pt" ? nf(2).format(x) : nf(0).format(Math.round(x * 1000));
export const pct = (x: number | null | undefined, d = 1) => (x == null ? "–" : (x > 0 ? "+" : "") + nf(d).format(x) + "%");
export const day = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;
export const fullDate = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}`;

export const STAGE_LABEL: Record<string, string> = {
  D: "Pha D", near: "Sát trần", E: "Pha E?", failed: "SOS hỏng", BC: "Pha B/C", below: "Dưới hỗ trợ", new: "Mới tạo đáy",
};
export const GROUP_LABEL: Record<string, string> = {
  ck: "Chứng khoán", bds: "Bất động sản", nh: "Ngân hàng", dtc: "Đầu tư công", thep: "Thép", wl: "Watchlist",
};
