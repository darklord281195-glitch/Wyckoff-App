"use client";
import { fullDate, num, pct, type Fundamentals } from "@/lib/api";

const ty = (x: number | null | undefined) => (x == null ? "–" : num(x, Math.abs(x) >= 100 ? 0 : 1) + " tỷ");
const quarter = (f: string) => `Q${Math.floor((+f.slice(5, 7) - 1) / 3) + 1}/${f.slice(0, 4)}`;

type Level = "good" | "mid" | "bad" | "na";
const TONE: Record<Level, { bg: string; fg: string }> = {
  good: { bg: "rgba(20, 150, 106, .12)", fg: "var(--up)" },
  mid: { bg: "rgba(214, 158, 46, .15)", fg: "var(--warn)" },
  bad: { bg: "rgba(210, 69, 59, .12)", fg: "var(--down)" },
  na: { bg: "var(--grid)", fg: "var(--muted)" },
};
type Row = { key: string; label: string; meaning: string; value: string; level: Level; verdict: string;
  sector?: number | null; sectorText?: string; better?: "high" | "low" };

/** Chỉ số cơ bản từ BCTC quý (chỉ báo cáo đã công bố tới ngày xem), diễn giải cho người mới: mỗi chỉ số có câu giải thích,
 *  nhãn Tốt / Trung bình / Yếu theo ngưỡng thông dụng và trung vị ngành để so sánh. Thông tin bối cảnh, không phải điều kiện mua. */
export default function FundamentalsCard({ f, at }: { f: Fundamentals | null; at: string | null }) {
  if (!f) return null;
  if (!f.fiscal && !f.pe) return <section className="card"><h2>Cơ bản</h2>
    <p className="muted" style={{ margin: 0 }}>Chưa có số liệu BCTC{f.error ? ` (${f.error})` : ""}.</p></section>;

  const sec = f.sector ?? null;
  const loss = f.np_ttm != null && f.np_ttm < 0;
  const g = f.np_growth;
  const margin = f.np_ttm != null && f.revenue_ttm ? f.np_ttm / f.revenue_ttm * 100 : null;
  const peg = f.pe != null && !loss && g != null && g > 0 && g < 999 ? f.pe / g : null;
  const rows: Row[] = [];

  if (f.np_ttm != null) rows.push({ key: "np", label: "Lãi 1 năm gần nhất", value: ty(f.np_ttm),
    meaning: "Lợi nhuận sau thuế thuộc cổ đông, cộng 4 quý gần nhất.",
    level: loss ? "bad" : "good", verdict: loss ? "Đang lỗ" : "Có lãi" });
  if (g != null) rows.push({ key: "growth", label: "Lãi tăng so với năm trước", value: g >= 999 ? "từ lỗ sang lãi" : pct(g),
    meaning: "4 quý gần nhất so với 4 quý trước đó. Trên 15% là tăng nhanh.",
    level: g >= 999 || g >= 15 ? "good" : g >= 0 ? "mid" : "bad",
    verdict: g >= 999 ? "Hết lỗ" : g >= 15 ? "Tăng nhanh" : g >= 0 ? "Tăng chậm" : "Giảm",
    sector: sec?.np_growth, sectorText: sec?.np_growth != null ? pct(sec.np_growth) : undefined, better: "high" });
  if (f.roe != null) rows.push({ key: "roe", label: "ROE · hiệu quả dùng vốn", value: num(f.roe, 1) + "%",
    meaning: `Mỗi 100 đồng vốn của cổ đông lãi ${num(f.roe, 1)} đồng/năm. Từ 15% là tốt; dưới 10% thấp (gửi tiết kiệm ~5–6%).`,
    level: f.roe >= 15 ? "good" : f.roe >= 10 ? "mid" : "bad", verdict: f.roe >= 15 ? "Hiệu quả" : f.roe >= 10 ? "Khá" : "Thấp",
    sector: sec?.roe, sectorText: sec?.roe != null ? num(sec.roe, 1) + "%" : undefined, better: "high" });
  if (margin != null) rows.push({ key: "margin", label: "Biên lợi nhuận", value: num(margin, 1) + "%",
    meaning: `Mỗi 100 đồng doanh thu còn lại ${num(margin, 1)} đồng lãi (doanh thu 1 năm ${ty(f.revenue_ttm)}). Khác nhau nhiều giữa các ngành, nên so với ngành.`,
    level: margin >= 15 ? "good" : margin >= 5 ? "mid" : "bad", verdict: margin >= 15 ? "Cao" : margin >= 5 ? "Trung bình" : "Mỏng",
    sector: sec?.margin, sectorText: sec?.margin != null ? num(sec.margin, 1) + "%" : undefined, better: "high" });
  if (f.debt_equity != null) {
    const d = f.debt_equity;
    rows.push({ key: "debt", label: "Nợ vay / vốn chủ", value: num(d, 2) + " lần",
      meaning: d === 0 ? "Nguồn dữ liệu ghi 0 đồng nợ vay: có thể công ty không vay, hoặc mẫu báo cáo khác. Nên đối chiếu BCTC gốc."
        : "Vay bao nhiêu so với vốn tự có. Dưới 0,5 an toàn; trên 1,5 rủi ro khi lãi suất tăng.",
      level: d === 0 ? "na" : d < 0.5 ? "good" : d <= 1.5 ? "mid" : "bad",
      verdict: d === 0 ? "Cần kiểm tra" : d < 0.5 ? "An toàn" : d <= 1 ? "Vừa phải" : d <= 1.5 ? "Khá cao" : "Cao",
      sector: sec?.debt_equity, sectorText: sec?.debt_equity != null ? num(sec.debt_equity, 2) + " lần" : undefined, better: "low" });
  }
  if (f.pe != null) rows.push({ key: "pe", label: "P/E · giá bằng mấy năm lãi", value: num(f.pe, 1),
    meaning: loss ? "Công ty đang lỗ nên P/E không có ý nghĩa."
      : peg != null ? `Bỏ ${num(f.pe, 1)} đồng để mua 1 đồng lãi/năm. Chia cho tốc độ tăng lãi: ${num(f.pe, 1)} ÷ ${num(g, 0)} = ${num(peg, 2)} (dưới 1 là rẻ so với tăng trưởng).`
      : `Bỏ ${num(f.pe, 1)} đồng để mua 1 đồng lãi/năm. Thị trường VN thường quanh 12–14.`,
    level: loss ? "na" : peg != null ? (peg < 1 ? "good" : peg <= 2 ? "mid" : "bad") : f.pe < 10 ? "good" : f.pe <= 18 ? "mid" : "bad",
    verdict: loss ? "Không tính" : peg != null ? (peg < 1 ? "Rẻ so với tăng trưởng" : peg <= 2 ? "Hợp lý" : "Đắt so với tăng trưởng")
      : f.pe < 10 ? "Thấp" : f.pe <= 18 ? "Vừa" : "Cao",
    sector: sec?.pe, sectorText: sec?.pe != null ? num(sec.pe, 1) : undefined, better: "low" });
  if (f.mcap != null) rows.push({ key: "mcap", label: "Vốn hóa", value: num(f.mcap) + " tỷ",
    meaning: "Giá trị cả công ty trên sàn (giá × số cổ phiếu). Công ty nhỏ thường biến động mạnh hơn.",
    level: "na", verdict: f.mcap >= 10000 ? "Lớn" : f.mcap >= 1000 ? "Vừa" : "Nhỏ" });

  // tóm tắt bằng lời từ các nhãn
  const lv = (k: string) => rows.find((r) => r.key === k)?.level;
  const parts: string[] = [];
  if (loss) parts.push("Công ty đang lỗ");
  else if (g != null) parts.push(g >= 999 ? "Lãi trở lại sau thua lỗ" : g >= 15 ? `Lãi tăng nhanh (${pct(g)})` : g >= 0 ? `Lãi tăng chậm (${pct(g)})` : `Lãi giảm (${pct(g)})`);
  if (f.roe != null) parts.push(lv("roe") === "good" ? "dùng vốn hiệu quả" : lv("roe") === "mid" ? "hiệu quả dùng vốn khá" : "dùng vốn chưa hiệu quả");
  if (f.debt_equity != null && f.debt_equity > 0) parts.push(lv("debt") === "good" ? "ít nợ vay" : lv("debt") === "bad" ? "nợ vay cao" : "nợ vay vừa phải");
  if (f.pe != null && !loss) parts.push(lv("pe") === "good" ? (peg != null ? "giá rẻ so với tốc độ tăng lãi" : "giá thấp")
    : lv("pe") === "mid" ? "giá hợp lý" : (peg != null ? "giá đắt so với tốc độ tăng lãi" : "giá cao"));
  const summary = parts.length ? parts[0] + (parts.length > 1 ? ", " + parts.slice(1).join(", ") : "") + "." : "";
  const count = (l: Level) => rows.filter((r) => r.level === l).length;

  const cmp = (r: Row) => {
    if (r.sector == null || r.sectorText == null) return <span className="muted">–</span>;
    const v = r.key === "growth" ? g : r.key === "roe" ? f.roe : r.key === "margin" ? margin : r.key === "debt" ? f.debt_equity : f.pe;
    if (v == null || (r.key === "pe" && loss) || (r.key === "debt" && v === 0) || (r.key === "growth" && (v ?? 0) >= 999)) return <span>{r.sectorText}</span>;
    const better = r.better === "high" ? v > r.sector : v < r.sector;
    return <span>{r.sectorText} <span className={better ? "up" : "down"} style={{ fontSize: 12.5 }}>{better ? "· tốt hơn ngành" : "· kém hơn ngành"}</span></span>;
  };

  return (
    <section className="card" style={{ display: "grid", gap: 10 }}>
      <h2 style={{ margin: 0 }}>Cơ bản {f.fiscal && <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· 4 quý tới {quarter(f.fiscal)}
        {at ? `, đã công bố trước ${fullDate(at)}` : ""}</span>}</h2>
      {summary && <p style={{ margin: 0 }}><b>Tóm lại:</b> {summary}{" "}
        <span className="muted">({count("good")} tốt · {count("mid")} trung bình · {count("bad")} yếu)</span></p>}
      <div className="tbl stack">
        <table style={{ minWidth: 640 }}>
          <thead><tr><th>Chỉ số</th><th>Giá trị</th><th>Đánh giá</th>
            <th title="Trung vị các mã cùng ngành có BCTC: một nửa số công ty cao hơn, một nửa thấp hơn">
              Trung vị ngành{sec ? ` (${sec.n} mã)` : ""}</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td style={{ whiteSpace: "normal", minWidth: 260 }}>
                  <div style={{ fontWeight: 600 }}>{r.label}</div>
                  <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.45 }}>{r.meaning}</div>
                </td>
                <td className="n">{r.value}</td>
                <td><span className="pill" style={{ background: TONE[r.level].bg, color: TONE[r.level].fg }}>{r.verdict}</span></td>
                <td className="n" data-label={`Trung vị ngành${sec ? ` (${sec.n} mã)` : ""}`}>{cmp(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
        Ngưỡng Tốt / Trung bình / Yếu là mức thông dụng để tham khảo nhanh; ngành khác nhau thì mức “bình thường” khác nhau, nên xem
        thêm cột ngành{sec?.name ? ` (${sec.name})` : ""}. Chỉ để hiểu doanh nghiệp: backtest 2019–2026 cho thấy lọc tín hiệu Wyckoff theo
        tăng trưởng LNST hoặc ROE không cải thiện kết quả, nên app không dùng các chỉ số này để báo mua. Nguồn BCTC quý VNDirect, tải lại
        mỗi tuần; ROE trên vốn chủ bình quân. Ngân hàng/chứng khoán/bảo hiểm không tính biên lợi nhuận và nợ vay theo mẫu doanh nghiệp
        thường.{f.error ? ` Lỗi tải: ${f.error}.` : ""}
      </p>
    </section>
  );
}
