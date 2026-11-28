/**
 * Đọc Wyckoff theo kênh người dùng vẽ: cạnh dưới = hỗ trợ, cạnh trên = kháng cự.
 * Mỗi lần giá chạm / xuyên một cạnh (một "lượt chạm") được gắn nhãn, rồi suy ra Pha A–E.
 *
 * Kênh mở đầu bằng lượt chạm cạnh dưới -> tích lũy (SC, AR, ST, Spring, Test, UT, SOS, LPS);
 * mở đầu bằng cạnh trên -> phân phối (BC, AR, ST, UT/UTAD, SOW, LPSY).
 * Đây là luật đơn giản hóa để đọc nhanh, chưa backtest: dùng như gợi ý, không phải tín hiệu.
 */
import type { Ohlcv } from "./api";

export type ChEvent = { i: number; k: string; pos: "low" | "high"; price: number; vx: number | null };
export type ChPhase = { ph: string; i0: number; i1: number };
export type ChWyckoff = {
  kind: "acc" | "reacc" | "dist" | "redist"; title: string;
  events: ChEvent[]; phases: ChPhase[]; now: string; advice: string; tone: "good" | "warn" | "bad" | "info";
};

const TOL = 0.12;        // trong 12% độ cao kênh tính từ cạnh = chạm cạnh
const PEN = 0.03;        // xuyên quá cạnh > 3% độ cao kênh = xuyên thật (Spring / UT)
const GAP = 2;           // lượt chạm cho phép rời cạnh tối đa 2 nến mà vẫn tính là một lượt

type Run = { side: "low" | "high"; a: number; b: number; e: number; out: number; first: number; open: boolean };

const TITLE = { acc: "Tích lũy", reacc: "Tái tích lũy", dist: "Phân phối", redist: "Tái phân phối" };

export function channelWyckoff(rows: Ohlcv[], i0: number, lo: (i: number) => number, hi: (i: number) => number): ChWyckoff | null {
  const n = rows.length;
  if (i0 < 0 || i0 >= n - 5) return null;
  const H = (i: number) => Math.max(hi(i) - lo(i), 1e-9);
  const vx = (i: number) => {
    const w = rows.slice(Math.max(0, i - 20), i);
    if (w.length < 5) return null;
    const m = w.reduce((s, r) => s + r.v, 0) / w.length;
    return m > 0 ? Math.round(rows[i].v / m * 10) / 10 : null;
  };
  const zone = (i: number): "low" | "high" | null => {
    const r = rows[i], L = r.l <= lo(i) + TOL * H(i), U = r.h >= hi(i) - TOL * H(i);
    if (L && U) return r.c - lo(i) < hi(i) - r.c ? "low" : "high";
    return L ? "low" : U ? "high" : null;
  };
  const outside = (i: number, side: "low" | "high") => (side === "low" ? rows[i].c < lo(i) : rows[i].c > hi(i));

  // ---- gom các lượt chạm
  const runs: Run[] = [];
  let cur: Run | null = null, gap = 0;
  const close = () => {
    if (!cur) return;
    const ids = Array.from({ length: cur.b - cur.a + 1 }, (_, j) => cur!.a + j);
    const side = cur.side;
    cur.e = side === "low" ? ids.reduce((x, i) => (rows[i].l - lo(i) < rows[x].l - lo(x) ? i : x))
      : ids.reduce((x, i) => (rows[i].h - hi(i) > rows[x].h - hi(x) ? i : x));
    const outs = ids.filter((i) => outside(i, side));
    cur.out = outs.length; cur.first = outs[0] ?? cur.e;
    runs.push(cur); cur = null;
  };
  for (let i = i0; i < n; i++) {
    const z = zone(i);
    if (cur && (z === cur.side || (z == null && gap < GAP))) {
      if (z === cur.side) { cur.b = i; gap = 0; } else gap++;
      continue;
    }
    close(); gap = 0;
    if (z) cur = { side: z, a: i, b: i, e: i, out: 0, first: i, open: false };
  }
  if (cur) { (cur as Run).open = (cur as Run).b >= n - 1 - GAP; close(); }
  if (!runs.length) return null;

  const before = rows[Math.max(0, i0 - 120)].c, start = rows[i0].c;
  const acc = runs[0].side === "low";
  const kind: ChWyckoff["kind"] = acc ? (start >= before * 1.15 ? "reacc" : "acc") : (start <= before * 0.87 ? "redist" : "dist");
  const ev: ChEvent[] = [];
  const add = (i: number, k: string, pos: "low" | "high") =>
    ev.push({ i, k, pos, price: pos === "low" ? rows[i].l : rows[i].h, vx: vx(i) });
  const pen = (r: Run) => (r.side === "low" ? (lo(r.e) - rows[r.e].l) : (rows[r.e].h - hi(r.e))) / H(r.e);

  // mốc chính (chỉ số nến, -1 = chưa có)
  let A = -1, AR = -1, ST1 = -1, C = -1, CT = -1, BRK = -1, BACK = -1, FAIL = -1;
  // tích lũy:  A = SC, C = Spring, CT = Test, BRK = SOS, BACK = LPS, FAIL = gãy hỗ trợ
  // phân phối: A = BC, C = UTAD, BRK = SOW, BACK = LPSY, FAIL = bứt lên giữ được (phân phối hỏng)
  const home = acc ? "low" : "high";               // cạnh "đáy" của sơ đồ (SC / BC)
  for (const r of runs) {
    const deep = pen(r) > PEN || r.out > 0;
    if (r.side === home) {
      if (r.out >= 3 && r.open) { FAIL = r.first; add(r.first, acc ? "Gãy hỗ trợ" : "Bứt lên (phân phối hỏng)", r.side); break; }
      if (A < 0) { A = r.e; add(r.e, acc ? "SC" : "BC", r.side); continue; }
      if (AR < 0) {                                // chưa có AR: lượt chạm này chỉ thay SC / BC nếu cực trị hơn
        if (acc ? rows[r.e].l < rows[A].l : rows[r.e].h > rows[A].h) {
          ev.splice(ev.findIndex((e) => e.i === A), 1); A = r.e; add(r.e, acc ? "SC" : "BC", r.side);
        }
        continue;
      }
      if (deep && AR >= 0 && ST1 >= 0 && C < 0) { C = r.e; add(r.e, acc ? "Spring" : "UTAD", r.side); continue; }
      if (C >= 0 && CT < 0) { CT = r.e; add(r.e, acc ? "Test" : "ST sau UTAD", r.side); continue; }
      if (ST1 < 0) ST1 = r.e;
      add(r.e, deep ? (acc ? "ST (xuyên)" : "UT") : "ST", r.side);
    } else {
      if (A < 0) continue;                         // chạm cạnh kia trước mốc mở đầu: bỏ qua
      if (AR < 0 && r.out === 0) { AR = r.e; add(r.e, "AR", r.side); continue; }
      if (r.out >= 2 && r.open) {                  // đang ở ngoài kênh tới phiên mới nhất: phá vỡ
        BRK = r.first; add(r.first, acc ? "SOS" : "SOW", r.side);
        const after = Array.from({ length: r.b - r.first }, (_, q) => r.first + 1 + q);
        if (after.length >= 3) {
          const b = acc ? after.reduce((x, i) => (rows[i].l < rows[x].l ? i : x)) : after.reduce((x, i) => (rows[i].h > rows[x].h ? i : x));
          if (b < n - 1 && b > r.first + 1) { BACK = b; add(b, acc ? "LPS" : "LPSY", acc ? "low" : "high"); }
        }
        continue;
      }
      if (r.out >= 3) { add(r.first, acc ? "SOS hụt" : "SOW hụt", r.side); continue; }
      if (deep) { add(r.e, acc ? "UT" : "Thủng hụt", r.side); continue; }
      if (AR < 0) { AR = r.e; add(r.e, "AR", r.side); continue; }
      add(r.e, acc ? "Chạm trần" : "Chạm đáy", r.side);
    }
  }
  if (A < 0) return null;
  ev.sort((x, y) => x.i - y.i);

  // ---- pha
  const last = n - 1, ph: ChPhase[] = [];
  const push = (p: string, a: number, b: number) => { if (a <= b && a <= last) ph.push({ ph: p, i0: a, i1: Math.min(b, last) }); };
  const endB = FAIL >= 0 ? FAIL - 1 : C >= 0 ? C - 1 : BRK >= 0 ? BRK - 1 : last;
  const endA = ST1 >= 0 ? Math.min(ST1, endB) : endB;
  push("A", A, endA);
  push("B", endA + 1, endB);
  if (C >= 0 && FAIL < 0) {
    const cEnd = CT >= 0 ? CT : Math.min(C + 3, last);
    push("C", C, cEnd);
    push("D", cEnd + 1, BACK >= 0 ? BACK : last);
  } else if (BRK >= 0 && FAIL < 0) {
    push("D", BRK, BACK >= 0 ? BACK : last);
  }
  if (BACK >= 0 && FAIL < 0) {
    const pk = acc ? Math.max(...rows.slice(BRK, BACK + 1).map((r) => r.h)) : Math.min(...rows.slice(BRK, BACK + 1).map((r) => r.l));
    const go = rows.findIndex((r, i) => i > BACK && (acc ? r.c > pk : r.c < pk));
    if (go > 0) { const d = ph.find((p) => p.ph === "D"); if (d) d.i1 = go - 1; push("E", go, last); }
  }
  if (FAIL >= 0) push(acc ? "Gãy" : "Hỏng", FAIL, last);
  const now = ph.length ? ph[ph.length - 1].ph : "A";

  // ---- kết luận
  const T: Record<string, [ChWyckoff["tone"], string]> = acc ? {
    A: ["info", "Pha A: vừa dừng giảm (SC, AR). Chưa mua, chờ ST quay về cạnh dưới với KL nhỏ hơn SC."],
    B: ["info", "Pha B: đang tích lũy trong kênh. Chờ Spring / Test ở cạnh dưới (KL cạn) hoặc SOS qua cạnh trên có KL; mua sớm ở cạnh dưới chỉ khi KL cạn."],
    C: ["good", "Pha C: đã có Spring. Điểm mua: Test lại với KL thấp, giữ trên đáy Spring; cắt lỗ khi thủng đáy Spring."],
    D: ["good", BRK >= 0 ? "Pha D: đã SOS qua cạnh trên. Mua nhịp lùi về sát cạnh trên (LPS / Backup) khi KL giảm; hỏng nếu đóng cửa lại sâu trong kênh."
      : "Pha D: giá đi lên từ cạnh dưới sau Spring / Test. Chờ SOS qua cạnh trên có KL, hoặc mua LPS trong kênh."],
    E: ["warn", "Pha E: đã rời vùng, đang trong xu hướng tăng. Không mua đuổi, chỉ mua nhịp lùi."],
    "Gãy": ["bad", "Thủng cạnh dưới và không lấy lại được: kênh tích lũy hỏng, đứng ngoài."],
  } : {
    A: ["warn", "Pha A: vừa dừng tăng (BC, AR). Không mua mới."],
    B: ["warn", "Pha B phân phối: giá đi ngang dưới vùng đỉnh, tránh mua; chờ xem UTAD hoặc SOW."],
    C: ["bad", "Pha C: đã có UTAD (bứt hụt qua cạnh trên). Rủi ro giảm cao, không mua."],
    D: ["bad", "Pha D: đã SOW thủng cạnh dưới. Bán / đứng ngoài; nhịp hồi về cạnh dưới (LPSY) là điểm thoát."],
    E: ["bad", "Pha E: xu hướng giảm."],
    "Hỏng": ["info", "Đã bứt qua cạnh trên và giữ được: kịch bản phân phối hỏng, có thể là tái tích lũy."],
  };
  const [tone, advice] = T[now] ?? ["info", ""];
  return { kind, title: TITLE[kind], events: ev, phases: ph, now, advice, tone };
}
