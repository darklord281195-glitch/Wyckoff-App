"use client";
import { useState } from "react";

type Note = { name: string; what: string; vol: string; act: string };

/** Ý nghĩa từng mốc Wyckoff (tích lũy). Dùng cho sơ đồ mẫu và tooltip bảng sự kiện. */
export const WYCKOFF_NOTES: Record<string, Note> = {
  PS: { name: "Preliminary Support – Hỗ trợ sơ bộ",
    what: "Lực mua lớn đầu tiên xuất hiện sau đợt giảm dài, làm đà giảm chậm lại nhưng chưa dừng hẳn.",
    vol: "KL và biên độ tăng rõ so với trước.", act: "Chưa mua. Chỉ là dấu hiệu đợt giảm sắp kết thúc." },
  SC: { name: "Selling Climax – Cao trào bán",
    what: "Phiên hoặc vài phiên bán tháo hoảng loạn; tay to hấp thụ lượng cung lớn từ nhà đầu tư nhỏ. Tạo đáy của vùng tích lũy.",
    vol: "KL rất lớn (cao trào), biên độ rộng, thường đóng cửa rút chân.", act: "Chưa mua. Đánh dấu đáy SC làm hỗ trợ của vùng." },
  AR: { name: "Automatic Rally – Hồi phục tự động",
    what: "Cung cạn tạm thời sau SC nên giá bật lên nhanh. Đỉnh AR là trần (kháng cự) của vùng tích lũy.",
    vol: "KL thường giảm dần trong nhịp hồi.", act: "Chưa mua. Vùng SC–AR là khung để theo dõi Pha B." },
  ST: { name: "Secondary Test – Kiểm tra lại",
    what: "Giá quay về gần đáy SC để kiểm tra lượng cung còn lại. Đáy ST cao hơn hoặc ngang SC là tốt.",
    vol: "KL thấp hơn hẳn SC: cung đã cạn.", act: "Chưa mua. KL càng thấp thì vùng tích lũy càng đáng tin." },
  Spring: { name: "Spring – Rũ bỏ (Pha C, mẫu 1)",
    what: "Giá thủng đáy vùng rồi nhanh chóng đóng cửa trở lại bên trong, quét sạch lệnh cắt lỗ cuối cùng. Phép thử cuối trước khi tăng.",
    vol: "KL thấp là Spring đẹp. KL lớn mà không lấy lại được đáy thì có thể là gãy thật.",
    act: "Chỉ thăm dò, tối đa 1/3 tỷ trọng, cắt lỗ dưới đáy Spring. Backtest: Spring chưa xác nhận lỗ nhiều." },
  Test: { name: "Test – Kiểm tra Spring",
    what: "Giá lùi lại gần đáy Spring nhưng không thủng, xác nhận cung đã hết.",
    vol: "KL thấp hơn Spring.", act: "Có thể tăng tỷ trọng nhẹ nếu giữ được đáy." },
  "Đáy nâng": { name: "Đáy nâng – Pha C của mẫu 2 (không Spring)",
    what: "Nhịp giảm cuối dừng TRÊN đáy SC, không cần rũ bỏ: cầu đã đủ mạnh. Gặp thường xuyên hơn Spring.",
    vol: "KL thấp, biên độ hẹp.", act: "Tương đương Test sau Spring: có thể thăm dò nhỏ, xác nhận khi có SOS." },
  SOS: { name: "Sign of Strength – Dấu hiệu sức mạnh (Pha D)",
    what: "Phiên tăng mạnh vượt trần AR: cầu đã chiếm ưu thế, giá chuẩn bị rời vùng.",
    vol: "KL lớn (app yêu cầu ≥ 1,5 lần TB20), biên độ rộng, đóng cửa gần đỉnh.",
    act: "Không mua đuổi ngay phiên SOS. Chờ nhịp lùi (Backup/LPS)." },
  "Đỉnh hạ": { name: "Đỉnh hạ trong vùng tích lũy – cảnh báo",
    what: "Đỉnh hồi sau AR thấp hơn đỉnh trước, liên tiếp ≥ 2 lần: mỗi nhịp hồi yếu hơn, giá trượt dần từ trần về đáy. Cầu chưa vào.",
    vol: "Nhịp hồi KL thấp, nhịp giảm KL cao hơn là xác nhận cung còn chiếm ưu thế.",
    act: "Đừng tin Spring/ST khi chuỗi đỉnh hạ còn nguyên. Chờ giá đóng cửa vượt đỉnh hạ gần nhất với KL tăng." },
  "Đỉnh sau SOS": { name: "Đỉnh sau SOS",
    what: "Đỉnh cao nhất sau phiên vượt trần, trước nhịp lùi về.",
    vol: "Nếu KL tăng mà giá không lên thêm là có cung chặn.", act: "Chờ giá lùi về vùng trần cũ để tìm LPS." },
  LPS: { name: "Last Point of Support – Điểm hỗ trợ cuối (Pha D)",
    what: "Nhịp lùi sau SOS về gần trần cũ (nay thành hỗ trợ) và giữ được. Là điểm cuối cùng mua được với rủi ro thấp trước khi tăng giá.",
    vol: "KL nhịp lùi thấp hơn nhịp tăng (app: < 0,8 lần), KL phiên mua dưới TB20.",
    act: "Điểm mua chính. App chỉ báo khi đáy LPS giữ ≥ 2 phiên. Cắt lỗ dưới đáy LPS." },
  Markup: { name: "Markup – Tăng giá (Pha E)",
    what: "Giá rời hẳn vùng tích lũy và tăng theo xu hướng; các nhịp lùi nông, giữ trên đỉnh cũ.",
    vol: "KL tăng khi lên, giảm khi lùi.", act: "Không mua đuổi. Người đang giữ chốt dần ở T1/T2, dời cắt lỗ lên." },
};
WYCKOFF_NOTES["LPS?"] = WYCKOFF_NOTES.LPS;

/** Ý nghĩa các mốc phân phối (dùng để nhận biết khi nào nên thoát lệnh đang giữ). */
export const DIST_NOTES: Record<string, Note> = {
  PSY: { name: "Preliminary Supply – Cung sơ bộ",
    what: "Lực bán lớn đầu tiên sau đợt tăng dài; đà tăng chậm lại nhưng chưa dừng.",
    vol: "KL và biên độ tăng rõ, giá khó đi lên thêm.", act: "Người đang giữ: chuẩn bị chốt lời, không mua thêm." },
  BC: { name: "Buying Climax – Cao trào mua",
    what: "Phiên hoặc vài phiên tăng hưng phấn, nhà đầu tư nhỏ đổ tiền mua, tay to bán ra. Tạo đỉnh của vùng phân phối.",
    vol: "KL rất lớn, biên độ rộng, thường đóng cửa xa đỉnh phiên (app báo 💰 Chốt lời?).",
    act: "Chốt một phần, dời cắt lỗ sát. Đỉnh BC thành kháng cự của vùng." },
  AR: { name: "Automatic Reaction – Phản ứng giảm tự động",
    what: "Cầu cạn sau BC nên giá rơi nhanh. Đáy AR là hỗ trợ (đáy) của vùng phân phối.",
    vol: "KL lớn lúc rơi.", act: "Vùng BC–AR là khung để theo dõi. Thủng đáy AR là tín hiệu xấu." },
  ST: { name: "Secondary Test – Kiểm tra lại đỉnh",
    what: "Giá hồi lên gần đỉnh BC để kiểm tra lượng cầu còn lại. Không vượt được BC là cầu đã yếu.",
    vol: "KL thấp hơn BC; KL thấp mà giá không lên là cầu cạn.", act: "Cơ hội bán phần còn lại ở giá tốt." },
  UTAD: { name: "Upthrust After Distribution – Kéo vượt đỉnh giả (Pha C, mẫu 1)",
    what: "Giá vượt đỉnh vùng rồi nhanh chóng rơi lại vào trong, bẫy người mua phá đỉnh. Ngược với Spring.",
    vol: "KL lớn khi vượt đỉnh nhưng giá đóng cửa yếu.", act: "Không mua phá đỉnh. Người đang giữ: siết cắt lỗ hoặc bán." },
  "Đỉnh hạ": { name: "Đỉnh hạ – Pha C của mẫu 2 (không UTAD)",
    what: "Nhịp hồi cuối dừng DƯỚI đỉnh BC: cầu đã yếu tới mức không kéo nổi lên đỉnh cũ.",
    vol: "KL hồi thấp.", act: "Người đang giữ: bán dần. Không mua." },
  SOW: { name: "Sign of Weakness – Dấu hiệu suy yếu (Pha D)",
    what: "Phiên giảm mạnh thủng đáy AR: cung đã áp đảo, giá chuẩn bị rời vùng đi xuống.",
    vol: "KL lớn, biên độ rộng, đóng cửa gần đáy phiên.", act: "Thoát hết. Không bắt đáy." },
  LPSY: { name: "Last Point of Supply – Điểm cung cuối (Pha D)",
    what: "Nhịp hồi yếu sau SOW, chạm lại đáy cũ (nay thành kháng cự) rồi quay xuống. Cơ hội bán cuối cùng ở giá cao.",
    vol: "KL hồi thấp: cầu yếu.", act: "Bán nốt nếu còn giữ. Không mua." },
  Markdown: { name: "Markdown – Giảm giá (Pha E)",
    what: "Giá rời hẳn vùng phân phối, giảm theo xu hướng; các nhịp hồi nông.",
    vol: "KL tăng khi giảm, giảm khi hồi.", act: "Đứng ngoài, chờ vùng tích lũy mới (SC, AR…)." },
};

type Pt = { k: string; x: number; y: number; below?: boolean };
type Schema = { notes: Record<string, Note>; pts: Pt[]; path: string; top: [number, string]; bottom: [number, string];
  zone: [number, number]; label: string };
type Variant = "acc1" | "acc2" | "dist1" | "dist2" | "reacc" | "redist";

// toạ độ SVG; y càng lớn giá càng thấp. Phân phối là ảnh lật dọc của tích lũy (y -> 310 - y).
const ACC1: Schema = {
  notes: WYCKOFF_NOTES, label: "tích lũy mẫu 1", zone: [135, 685],
  top: [110, "Trần (đỉnh AR)"], bottom: [250, "Hỗ trợ (đáy SC)"],
  pts: [
    { k: "PS", x: 70, y: 175, below: true }, { k: "SC", x: 135, y: 250, below: true }, { k: "AR", x: 205, y: 110 },
    { k: "ST", x: 285, y: 238, below: true }, { k: "Spring", x: 545, y: 278, below: true },
    { k: "Test", x: 605, y: 246, below: true }, { k: "SOS", x: 685, y: 82 }, { k: "LPS", x: 745, y: 128, below: true },
    { k: "Markup", x: 865, y: 32 },
  ],
  path: "M10,40 L70,175 L100,150 L135,250 L205,110 L285,238 L345,135 L405,226 L465,125 L545,278 L575,215 " +
    "L605,246 L685,82 L745,128 L805,62 L830,85 L865,32",
};
// mẫu 2: Pha C là đáy nâng trên hỗ trợ, không có Spring/Test
const ACC2: Schema = {
  ...ACC1, label: "tích lũy mẫu 2",
  pts: [...ACC1.pts.filter((p) => p.k !== "Spring" && p.k !== "Test"), { k: "Đáy nâng", x: 560, y: 222, below: true }]
    .sort((a, b) => a.x - b.x),
  path: ACC1.path.replace("L545,278 L575,215 L605,246", "L560,222 L620,170"),
};
const flip = (s: string) => s.replace(/(\d+),(\d+)/g, (_, x, y) => `${x},${310 - +y}`);
const ACC_TO_DIST: Record<string, string> = { PS: "PSY", SC: "BC", AR: "AR", ST: "ST", Spring: "UTAD", Test: "",
  "Đáy nâng": "Đỉnh hạ", SOS: "SOW", LPS: "LPSY", Markup: "Markdown" };
const toDist = (a: Schema, label: string): Schema => ({
  notes: DIST_NOTES, label, zone: a.zone, top: [60, "Kháng cự (đỉnh BC)"], bottom: [200, "Hỗ trợ (đáy AR)"],
  pts: a.pts.map((p) => ({ k: ACC_TO_DIST[p.k], x: p.x, y: 310 - p.y, below: !p.below })).filter((p) => p.k),
  path: flip(a.path),
});
// tái tích lũy: đi lên từ trái, nghỉ trong vùng (nhịp điều chỉnh nông), rồi tăng tiếp
const REACC: Schema = {
  label: "tái tích lũy", zone: [135, 685], top: [110, "Trần (đỉnh nhịp tăng trước)"], bottom: [200, "Hỗ trợ (đáy AR)"],
  notes: { ...WYCKOFF_NOTES,
    "Đỉnh": { name: "Đỉnh nhịp tăng – mở đầu tái tích lũy (Pha A)",
      what: "Đà tăng trước dừng lại, thường kèm KL lớn. Không phải đỉnh xu hướng: giá chỉ nghỉ để hấp thụ lượng hàng chốt lời.",
      vol: "KL lớn rồi giảm dần.", act: "Đang giữ: có thể chốt một phần. Chưa mua thêm." },
    AR: { name: "Automatic Reaction – Nhịp giảm tự động",
      what: "Nhịp điều chỉnh đầu tiên sau đỉnh; đáy AR là hỗ trợ của vùng. Ở tái tích lũy, nhịp này thường nông (< 20%).",
      vol: "KL giảm khi giá giảm là tốt (chỉ chốt lời, không phải bán tháo).", act: "Đánh dấu đáy AR làm hỗ trợ." },
    ST: { name: "Secondary Test – Kiểm tra lại đỉnh",
      what: "Giá hồi lên gần trần vùng; chưa vượt được thì tiếp tục đi ngang (Pha B).",
      vol: "KL thấp hơn lúc tạo đỉnh.", act: "Chưa mua. Chờ Spring/Shakeout hoặc SOS." } },
  pts: [
    { k: "Đỉnh", x: 135, y: 110 }, { k: "AR", x: 205, y: 200, below: true }, { k: "ST", x: 285, y: 118 },
    { k: "Spring", x: 545, y: 228, below: true }, { k: "Test", x: 605, y: 196, below: true }, { k: "SOS", x: 685, y: 80 },
    { k: "LPS", x: 745, y: 118, below: true }, { k: "Markup", x: 865, y: 34 },
  ],
  path: "M10,290 L60,200 L85,215 L135,110 L205,200 L285,118 L345,190 L405,125 L465,195 L545,228 L575,170 " +
    "L605,196 L685,80 L745,118 L805,55 L830,75 L865,34",
};
// tái phân phối: ảnh lật của tái tích lũy - đi xuống từ trái, nghỉ, rồi giảm tiếp
const REDIST: Schema = {
  label: "tái phân phối", zone: [135, 685], top: [110, "Kháng cự (đỉnh AR)"], bottom: [200, "Hỗ trợ (đáy nhịp giảm trước)"],
  notes: { ...DIST_NOTES,
    "Đáy": { name: "Đáy nhịp giảm – mở đầu tái phân phối (Pha A)",
      what: "Đà giảm trước tạm dừng. Không phải đáy xu hướng: giá chỉ nghỉ trước khi giảm tiếp.",
      vol: "KL lớn rồi giảm dần.", act: "Không bắt đáy. Chờ xem vùng là tích lũy hay tái phân phối." },
    AR: { name: "Automatic Rally – Nhịp hồi tự động",
      what: "Nhịp hồi đầu tiên sau đáy; đỉnh AR là kháng cự của vùng. Ở tái phân phối nhịp hồi yếu, KL thấp.",
      vol: "KL thấp khi hồi: cầu yếu.", act: "Không mua theo nhịp hồi." },
    ST: { name: "Secondary Test – Kiểm tra lại đáy",
      what: "Giá quay về gần đáy vùng; KL không giảm (cung vẫn còn) là dấu hiệu tái phân phối.",
      vol: "KL cao khi về đáy là xấu.", act: "Không mua." } },
  pts: REACC.pts.map((p) => ({ k: { "Đỉnh": "Đáy", AR: "AR", ST: "ST", Spring: "UTAD", Test: "", SOS: "SOW", LPS: "LPSY",
    Markup: "Markdown" }[p.k] ?? "", x: p.x, y: 310 - p.y, below: !p.below })).filter((p) => p.k),
  path: flip(REACC.path),
};
const SCHEMAS: Record<Variant, Schema> = {
  acc1: ACC1, acc2: ACC2, dist1: toDist(ACC1, "phân phối mẫu 1"), dist2: toDist(ACC2, "phân phối mẫu 2"),
  reacc: REACC, redist: REDIST,
};
const TABS: [Variant, string][] = [["acc1", "Tích lũy 1 (Spring)"], ["acc2", "Tích lũy 2 (đáy nâng)"],
  ["dist1", "Phân phối 1 (UTAD)"], ["dist2", "Phân phối 2 (đỉnh hạ)"],
  ["reacc", "Tái tích lũy (giữa xu hướng tăng)"], ["redist", "Tái phân phối (giữa xu hướng giảm)"]];
const PHASES = [["A", 20, 245], ["B", 245, 505], ["C", 505, 635], ["D", 635, 790], ["E", 790, 890]] as const;

/** Sơ đồ mẫu Wyckoff 4 biến thể; rê chuột, chạm hoặc Tab vào từng mốc để xem ý nghĩa.
 *  variant/phase: mẫu và pha của mã (backend classify); "acc" = tích lũy chưa rõ mẫu 1 hay 2. */
export default function WyckoffSchematic({ variant, phase }: { variant?: string | null; phase?: string | null }) {
  const [v, setV] = useState<Variant>(variant === "acc" ? "acc1" : (variant as Variant) || "acc1");
  const [on, setOn] = useState<string | null>(null);
  const S = SCHEMAS[v];
  const p = S.pts.find((x) => x.k === on);
  const n = on ? S.notes[on] : null;
  const mine = (t: Variant) => t === variant || (variant === "acc" && t.startsWith("acc"));   // mẫu của mã này
  const here = mine(v) ? PHASES.find(([ph]) => ph === phase) : undefined;

  return (
    <div style={{ position: "relative" }}>
      <div className="tabs" style={{ marginBottom: 8 }}>
        {TABS.map(([t, label]) => (
          <button key={t} className={v === t ? "on" : ""} onClick={() => { setV(t); setOn(null); }}>
            {label}{mine(t) ? " ●" : ""}</button>
        ))}
      </div>
      <svg viewBox="0 0 900 310" role="img" aria-label={`Sơ đồ mẫu ${S.label} Wyckoff`} style={{ width: "100%", height: "auto", display: "block" }}>
        {here && <rect x={here[1]} y={0} width={here[2] - here[1]} height={310} fill="var(--accent)" opacity={0.08} />}
        {PHASES.map(([ph, x0, x1], i) => (
          <g key={ph}>
            {i > 0 && <line x1={x0} x2={x0} y1={14} y2={300} stroke="var(--grid)" strokeDasharray="4 4" />}
            <text x={(x0 + x1) / 2} y={14} textAnchor="middle" fontSize={13} fontWeight={here?.[0] === ph ? 800 : 600}
              fill={here?.[0] === ph ? "var(--accent)" : "var(--muted)"}>Pha {ph}{here?.[0] === ph ? " ◀ đang ở đây" : ""}</text>
          </g>
        ))}
        <rect x={S.zone[0]} y={S.top[0]} width={S.zone[1] - S.zone[0]} height={S.bottom[0] - S.top[0]} fill="var(--accent-soft)" />
        <line x1={S.zone[0]} x2={S.zone[1]} y1={S.top[0]} y2={S.top[0]} stroke="var(--down)" strokeDasharray="6 4" />
        <line x1={S.zone[0]} x2={S.zone[1]} y1={S.bottom[0]} y2={S.bottom[0]} stroke="var(--up)" strokeDasharray="6 4" />
        <text x={S.zone[0] + 5} y={S.top[0] - 6} fontSize={11.5} fill="var(--down)">{S.top[1]}</text>
        <text x={S.zone[0] + 5} y={S.bottom[0] + 15} fontSize={11.5} fill="var(--up)">{S.bottom[1]}</text>
        <path d={S.path} fill="none" stroke="var(--fg)" strokeWidth={2} strokeLinejoin="round" />
        {S.pts.map((x) => (
          <g key={x.k} tabIndex={0} role="button" aria-label={S.notes[x.k].name} style={{ cursor: "pointer", outline: "none" }}
            onMouseEnter={() => setOn(x.k)} onMouseLeave={() => setOn(null)} onFocus={() => setOn(x.k)} onBlur={() => setOn(null)}
            onClick={() => setOn(on === x.k ? null : x.k)}>
            <circle cx={x.x} cy={x.y} r={14} fill="transparent" />
            <circle cx={x.x} cy={x.y} r={on === x.k ? 7 : 5.5} fill={on === x.k ? "var(--accent)" : "var(--surface)"}
              stroke="var(--accent)" strokeWidth={2} />
            <text x={x.x} y={x.below ? x.y + 22 : x.y - 12} textAnchor="middle" fontSize={12.5} fontWeight={700} fill="var(--accent)">{x.k}</text>
          </g>
        ))}
      </svg>
      {p && n && (
        <div role="tooltip" className="card" style={{
          position: "absolute", left: `clamp(0px, calc(${(p.x / 900) * 100}% - 160px), calc(100% - 320px))`,
          top: `${((p.below ? p.y + 30 : p.y + 14) / 310) * 100}%`, width: 320, maxWidth: "100%", zIndex: 5,
          padding: 12, fontSize: 13, lineHeight: 1.45, boxShadow: "0 6px 24px rgba(0,0,0,.18)", pointerEvents: "none",
        }}>
          <b>{n.name}</b>
          <p style={{ margin: "6px 0 0" }}>{n.what}</p>
          <p style={{ margin: "6px 0 0" }}><span className="muted">Khối lượng:</span> {n.vol}</p>
          <p style={{ margin: "6px 0 0" }}><span className="muted">Hành động:</span> {n.act}</p>
        </div>
      )}
      <p className="muted" style={{ margin: "6px 0 0", fontSize: 12.5 }}>
        Rê chuột (hoặc chạm) vào từng mốc để xem ý nghĩa. ● = mẫu mã này đang giống. Sơ đồ là mẫu lý tưởng; vùng thật thường không đủ mọi mốc.
      </p>
    </div>
  );
}
