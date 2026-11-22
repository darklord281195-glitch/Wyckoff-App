"use client";
import { fullDate, num, pct, type Fundamentals } from "@/lib/api";

const ty = (x: number | null | undefined) => (x == null ? "–" : num(x, x >= 100 ? 0 : 1) + " tỷ");
const quarter = (f: string) => `Q${Math.floor((+f.slice(5, 7) - 1) / 3) + 1}/${f.slice(0, 4)}`;

/** Chỉ số cơ bản từ BCTC quý (chỉ báo cáo đã công bố tới ngày xem). Thông tin bối cảnh, không phải điều kiện mua. */
export default function FundamentalsCard({ f, at }: { f: Fundamentals | null; at: string | null }) {
  if (!f) return null;
  if (!f.fiscal && !f.pe) return <section className="card"><h2>Cơ bản</h2>
    <p className="muted" style={{ margin: 0 }}>Chưa có số liệu BCTC{f.error ? ` (${f.error})` : ""}.</p></section>;
  const warn = (f.np_growth != null && f.np_growth < 0) || (f.roe != null && f.roe < 10) || (f.np_ttm != null && f.np_ttm < 0);
  return (
    <section className="card">
      <h2>Cơ bản {f.fiscal && <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· 4 quý tới {quarter(f.fiscal)}
        {at ? `, đã công bố trước ${fullDate(at)}` : ""}</span>}</h2>
      <dl className="kv" style={{ gridTemplateColumns: "auto 1fr auto 1fr" }}>
        <dt>LNST 4 quý</dt><dd className={(f.np_ttm ?? 0) < 0 ? "down" : ""}>{ty(f.np_ttm)}</dd>
        <dt>Tăng trưởng LNST</dt><dd className={f.np_growth == null ? "muted" : f.np_growth >= 0 ? "up" : "down"}>
          {f.np_growth == null ? "–" : f.np_growth >= 999 ? "từ lỗ sang lãi" : pct(f.np_growth)}</dd>
        <dt>ROE 4 quý</dt><dd className={f.roe == null ? "muted" : f.roe >= 15 ? "up" : f.roe < 10 ? "down" : ""}>
          {f.roe == null ? "–" : num(f.roe, 1) + "%"}</dd>
        <dt>Nợ vay / VCSH</dt><dd className={(f.debt_equity ?? 0) > 1.5 ? "down" : ""}>{f.debt_equity == null ? "–" : num(f.debt_equity, 2) + " lần"}</dd>
        <dt>Doanh thu 4 quý</dt><dd>{ty(f.revenue_ttm)}</dd>
        <dt>P/E · vốn hóa</dt><dd>{f.pe == null ? "–" : num(f.pe, 1)}{f.mcap != null ? ` · ${num(f.mcap)} tỷ` : ""}</dd>
      </dl>
      {warn && <p className="muted" style={{ margin: "8px 0 0" }}>Lợi nhuận giảm/âm hoặc ROE &lt; 10%: nếu nắm giữ dài hạn thì nên tìm hiểu thêm lý do.</p>}
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
        Chỉ để tham khảo: backtest 2019–2026 cho thấy lọc tín hiệu Wyckoff theo LNST tăng trưởng hoặc ROE &gt; 10% không cải thiện
        kết quả (còn kém hơn ở cả hai giai đoạn), nên app không dùng các chỉ số này để báo mua.{" "}
        Nguồn BCTC quý VNDirect, tải lại mỗi tuần. Tăng trưởng = LNST 4 quý gần nhất so với 4 quý trước đó; ROE trên VCSH bình quân.
        Ngân hàng/chứng khoán/bảo hiểm không tính doanh thu và nợ vay theo mẫu doanh nghiệp thường.{f.error ? ` Lỗi tải: ${f.error}.` : ""}
      </p>
    </section>
  );
}
