"use client";
import { useEffect, useState } from "react";
import { api, num, type PortfolioRisk, type Settings } from "@/lib/api";

const JSON_HDR = { "Content-Type": "application/json" };
const LIGHT_NAME: Record<string, string> = { green: "xanh", yellow: "vàng", red: "đỏ" };

/** Rủi ro danh mục: tổng rủi ro mở so với ngưỡng, số lệnh, tỷ trọng ngành, cảnh báo; sửa vốn và ngưỡng tại chỗ. */
export default function RiskCard({ reload }: { reload: number }) {
  const [r, setR] = useState<PortfolioRisk | null>(null);
  const [st, setSt] = useState<Settings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => Promise.all([api<PortfolioRisk>("/api/portfolio/risk"), api<Settings>("/api/settings")])
    .then(([a, b]) => { setR(a); setSt(b); setErr(null); }).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, [reload]);

  const save = async (k: keyof Settings, v: number) => {
    if (!st || !(v > 0) || v === st[k]) return;
    try { await api("/api/settings", { method: "PUT", headers: JSON_HDR, body: JSON.stringify({ [k]: v }) }); load(); }
    catch (e) { setErr(String(e)); }
  };
  const field = (k: keyof Settings, label: string, unit: string, w = 70, step = 1) => st && (
    <label className="muted">{label} <input type="number" defaultValue={st[k]} key={`${k}-${st[k]}`} min={0} step={step}
      style={{ width: w }} onBlur={(e) => save(k, +e.target.value)}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} /> {unit}</label>
  );

  if (err) return <section className="card"><h2>Rủi ro danh mục</h2><p className="muted">Lỗi: {err}</p></section>;
  if (!r || !st) return null;
  const over = r.heat > r.max_heat;
  const fill = Math.min(100, r.heat / r.max_heat * 100);

  return (
    <section className="card" style={{ display: "grid", gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Rủi ro danh mục</h2>
        <div className="row">
          {field("capital", "Vốn", "triệu", 90)}
          {field("risk_pct", "Rủi ro", "%/lệnh", 60, 0.1)}
          {field("max_heat", "Tối đa", "% vốn", 60, 0.5)}
          {field("max_pos", "", "lệnh", 50)}
          {field("max_sector", "1 ngành ≤", "%", 60, 5)}
        </div>
      </div>

      <div>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
          <span>Tổng rủi ro mở: <b className={over ? "down" : ""}>{num(r.heat, 1)}% vốn</b>{" "}
            <span className="muted">({num(r.total_risk / 1e6, 2)} triệu nếu mọi lệnh cùng về cắt lỗ)</span></span>
          <span className="muted">ngưỡng {num(r.max_heat, 1)}%</span>
        </div>
        <div className="meter" role="meter" aria-valuenow={r.heat} aria-valuemin={0} aria-valuemax={r.max_heat}
          aria-label="Tổng rủi ro mở so với ngưỡng">
          <div style={{ width: `${fill}%`, background: over ? "var(--down)" : r.heat > r.max_heat * 0.75 ? "#f59e0b" : "var(--up)" }} />
        </div>
      </div>

      <dl className="kv" style={{ gridTemplateColumns: "auto 1fr auto 1fr" }}>
        <dt>Số lệnh</dt><dd className={r.n > r.max_pos ? "down" : ""}>{r.n} / {r.max_pos}</dd>
        <dt>Giá trị đang giữ</dt><dd>{num(r.total_value / 1e6, 1)} triệu ({num(r.total_value / (r.capital * 1e6) * 100)}% vốn)</dd>
        <dt>Đèn thị trường</dt><dd>{LIGHT_NAME[r.light ?? ""] ?? "–"} · rủi ro gợi ý ×{num(r.factor, 1)}</dd>
        <dt>Rủi ro/lệnh mới</dt><dd>{num(st.risk_pct * r.factor, 2)}% vốn = {num(st.capital * st.risk_pct * r.factor / 100, 2)} triệu</dd>
      </dl>

      {r.sectors.length > 0 && <div style={{ display: "grid", gap: 4 }}>
        <span className="muted" style={{ fontSize: 12.5 }}>Tỷ trọng theo ngành (giá trị đang giữ)</span>
        {r.sectors.map((s) => (
          <div key={s.name} className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
            <span style={{ width: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
            <div className="meter" style={{ flex: 1 }}>
              <div style={{ width: `${s.pct}%`, background: s.pct > st.max_sector ? "var(--down)" : "var(--accent)" }} />
            </div>
            <span className="mono" style={{ width: 60, textAlign: "right" }}>{num(s.pct, 1)}%</span>
          </div>
        ))}
      </div>}

      {r.no_qty.length > 0 && <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
        Chưa tính được {r.no_qty.join(", ")}: lệnh chưa nhập số lượng.</p>}
      {r.warnings.length > 0
        ? <ul className="sig" style={{ margin: 0 }}>{r.warnings.map((w) => <li key={w}>⚠️ {w}</li>)}</ul>
        : r.n > 0 && <p className="up" style={{ margin: 0 }}>✓ Trong ngưỡng an toàn.</p>}
      <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
        Rủi ro mở = số cp còn giữ × (giá hiện tại − cắt lỗ hiện tại). Đèn vàng giảm rủi ro/lệnh còn ½, đèn đỏ không mở lệnh mới
        (backtest: đèn đỏ kỳ vọng âm). Cảnh báo cũng được gửi kèm tin Telegram cuối ngày.
      </p>
    </section>
  );
}
