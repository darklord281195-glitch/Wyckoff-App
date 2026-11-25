"use client";
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { Plan, api, num, pct, price, type PortfolioRisk, type Settings } from "@/lib/api";

const LS_KEY = "wyckoff-sizing";

/** Kế hoạch giao dịch: vùng vào, cắt lỗ, mục tiêu Nhân–Quả, điểm sẵn sàng, tính khối lượng và ghi nhận lệnh mua. */
/** readOnly: đang xem phiên cũ -> ẩn phần ghi nhận lệnh mua */
export default function PlanCard({ sym, plan, c, unit, readOnly }: { sym: string; plan: Plan; c: number; unit: "pt" | "k"; readOnly?: boolean }) {
  const [capital, setCapital] = useState(100);      // triệu đồng
  const [riskPct, setRiskPct] = useState(1);        // % vốn chấp nhận mất mỗi lệnh
  const [buyVnd, setBuyVnd] = useState(Math.round(c * 1000));   // giá mua thực tế (đồng)
  const [buyDate, setBuyDate] = useState("");                    // trống = phiên mới nhất
  const [buyQty, setBuyQty] = useState("");                      // trống = dùng số cp gợi ý
  const [buyStop, setBuyStop] = useState("");                    // đồng; trống = cắt lỗ theo kế hoạch
  const [msg, setMsg] = useState<string | null>(null);
  const [risk, setRisk] = useState<PortfolioRisk | null>(null);   // rủi ro danh mục hiện tại + hệ số theo đèn
  const [loaded, setLoaded] = useState(false);
  // vốn / % rủi ro dùng chung với trang Danh mục (backend /api/settings);
  // lần đầu: nếu backend còn mặc định mà trình duyệt có giá trị cũ (localStorage) thì chuyển lên backend
  useEffect(() => {
    (async () => {
      try {
        let s = await api<Settings>("/api/settings");
        let old: { capital?: number; riskPct?: number } = {};
        try { old = JSON.parse(localStorage.getItem(LS_KEY) ?? "{}"); } catch { /* không có storage */ }
        if (s.capital === 100 && s.risk_pct === 1 && (old.capital || old.riskPct)) {
          s = await api<Settings>("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ capital: old.capital ?? s.capital, risk_pct: old.riskPct ?? s.risk_pct }) });
        }
        try { localStorage.removeItem(LS_KEY); } catch { /* bỏ qua */ }
        setCapital(s.capital); setRiskPct(s.risk_pct);
        setRisk(await api<PortfolioRisk>("/api/portfolio/risk"));
      } catch { /* backend cũ chưa có API: giữ mặc định */ }
      setLoaded(true);
    })();
  }, []);
  // ghi lại khi người dùng sửa (chờ 0,6 giây sau lần gõ cuối)
  useEffect(() => {
    if (!loaded || !(capital > 0) || !(riskPct > 0)) return;
    const t = setTimeout(() => api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capital, risk_pct: riskPct }) }).catch(() => {}), 600);
    return () => clearTimeout(t);
  }, [capital, riskPct, loaded]);

  const entry = plan.entry_lo && plan.entry_hi ? (plan.entry_lo + plan.entry_hi) / 2 : null;
  const perShare = entry && plan.stop ? (entry - plan.stop) * 1000 : null;               // đồng/cp
  const factor = risk?.factor ?? 1;                     // đèn xanh 1 · vàng 0,5 · đỏ 0
  const effPct = riskPct * factor;
  const maxLoss = capital * 1e6 * effPct / 100;
  const heatAfter = risk ? risk.heat + effPct : null;   // tổng rủi ro mở (% vốn) nếu vào thêm lệnh này
  const shares = perShare && perShare > 0 ? Math.floor(maxLoss / perShare / 100) * 100 : 0;  // lô 100
  const value = entry ? shares * entry * 1000 : 0;
  const qty = +buyQty > 0 ? Math.floor(+buyQty) : shares;   // số cp thực mua; không nhập thì lấy gợi ý
  const parts = Object.entries(plan.ready?.parts ?? {});
  // cắt lỗ + mục tiêu được chốt theo kế hoạch tại ngày mua; sau đó trang Danh mục và Telegram báo khi cần bán
  const record = async () => {
    try {
      await api("/api/positions", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sym, entry_px: buyVnd / 1000, entry_d: buyDate || null, qty: qty || null, stop: +buyStop > 0 ? +buyStop / 1000 : null }) });
      setMsg("Đã ghi nhận.");
    } catch (e) { setMsg(String(e)); }
  };

  return (
    <section className="card" style={{ display: "grid", gap: 14 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Kế hoạch giao dịch · <span className="pill">{plan.kind}</span></h2>
        <span className="muted">Điểm sẵn sàng <b style={{ color: "var(--fg)" }}>{plan.ready?.score ?? "–"}</b>/100</span>
      </div>
      <p style={{ margin: 0 }}>{plan.trigger}</p>
      {(plan.steps?.length || plan.cancel) ? (
        <div style={{ borderLeft: "3px solid var(--up)", paddingLeft: 12 }}>
          <b>Kịch bản mua đẹp</b>
          {plan.steps?.length ? <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
            {plan.steps.map((s, i) => <li key={i} className={i === 0 && plan.selloff ? "down" : ""}>{s}</li>)}</ol> : null}
          {plan.cancel && <p style={{ margin: "6px 0 0" }}><b>Hủy kịch bản khi:</b> {plan.cancel}</p>}
        </div>
      ) : null}

      <div className="grid2">
        <div className="tbl">
          <table style={{ minWidth: 460 }}>
            <tbody>
              <tr><td className="muted">Vùng vào</td>
                <td className="n">{plan.entry_lo ? `${price(plan.entry_lo, unit)} – ${price(plan.entry_hi, unit)}` : "–"}
                  {plan.in_zone ? " 🎯 giá đang trong vùng" : ""}</td></tr>
              <tr><td className="muted">Cắt lỗ</td>
                <td><span className="n down">{price(plan.stop, unit)}</span> <span className="muted">({pct(plan.risk_pct)})</span><br />
                  <span className="muted" style={{ whiteSpace: "normal" }}>{plan.stop_reason}</span></td></tr>
              <tr><td className="muted">Cắt lỗ theo thời gian</td>
                <td style={{ whiteSpace: "normal" }}>Sau {plan.time_stop} phiên mà giá chưa chạm T1</td></tr>
              {plan.targets.map((t) => (
                <tr key={t.k}>
                  <td className="muted">{t.k}{t.k === plan.main_target ? " ⭐" : ""}</td>
                  <td><span className="n up">{price(t.price, unit)}</span>{" "}
                    <span className="muted">({pct(t.pct)} · lời/lỗ {t.rr != null ? num(t.rr, 1) : "–"})</span><br />
                    <span className="muted" style={{ whiteSpace: "normal" }}>{t.basis}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ display: "grid", gap: 10, alignContent: "start" }}>
          <div>
            <b>Tính khối lượng</b>
            <div className="row" style={{ marginTop: 6 }}>
              <label className="muted">Vốn <input id="capital" type="number" value={capital} min={1}
                onChange={(e) => setCapital(+e.target.value)} style={{ width: 90 }} /> triệu</label>
              <label className="muted">Rủi ro <input id="risk" type="number" value={riskPct} min={0.1} step={0.1}
                onChange={(e) => setRiskPct(+e.target.value)} style={{ width: 70 }} /> %/lệnh</label>
            </div>
            {unit === "k" && entry && perShare ? (
              <dl className="kv" style={{ marginTop: 8 }}>
                {factor < 1 && <><dt>Theo đèn</dt><dd className="down" style={{ fontFamily: "inherit" }}>
                  {factor === 0 ? "Đèn đỏ: không mở lệnh mới (backtest kỳ vọng âm)"
                    : `Đèn vàng: rủi ro giảm còn ${num(effPct, 2)}%/lệnh`}</dd></>}
                <dt>Lỗ tối đa</dt><dd>{num(maxLoss / 1e6, 2)} triệu</dd>
                <dt>Số cp gợi ý</dt><dd>{num(shares)} cp</dd>
                <dt>Giá trị lệnh</dt><dd>{num(value / 1e6, 1)} triệu ({num(value / (capital * 1e6) * 100)}% vốn)</dd>
                {risk && heatAfter != null && factor > 0 && <><dt>Rủi ro danh mục</dt>
                  <dd className={heatAfter > risk.max_heat ? "down" : ""}>
                    {num(risk.heat, 1)}% → {num(heatAfter, 1)}% vốn (ngưỡng {num(risk.max_heat, 1)}%)
                    {heatAfter > risk.max_heat ? " · vượt ngưỡng, nên không vào" : ""}</dd></>}
              </dl>
            ) : <p className="muted">Chưa có điểm vào để tính.</p>}
            {!readOnly && <div className="row" style={{ marginTop: 8 }}>
              <label className="muted">Giá mua <input id="buy-px" type="number" value={buyVnd} min={1} step={10}
                onChange={(e) => setBuyVnd(+e.target.value)} style={{ width: 100 }} /> đ</label>
              <label className="muted">Số lượng <input id="buy-qty" type="number" value={buyQty} min={1} step={100}
                placeholder={shares ? String(shares) : ""} onChange={(e) => setBuyQty(e.target.value)} style={{ width: 90 }} /> cp</label>
              <label className="muted">Cắt lỗ <input id="buy-stop" type="number" value={buyStop} min={1} step={10}
                placeholder={plan.stop ? String(Math.round(plan.stop * 1000)) : ""}
                onChange={(e) => setBuyStop(e.target.value)} style={{ width: 100 }} /> đ</label>
              <label className="muted">Ngày <input id="buy-d" type="date" value={buyDate}
                onChange={(e) => setBuyDate(e.target.value)} /></label>
              <button className="btn primary" onClick={record} disabled={!plan.stop && !(+buyStop > 0)}>
                Ghi nhận đã mua{qty ? ` ${num(qty)} cp` : ""}</button>
            </div>}
            {msg && <p className="muted" style={{ margin: "6px 0 0" }}>
              {msg} {msg.startsWith("Đã") && <Link href="/watchlist">Xem ở Danh mục</Link>}</p>}
          </div>
          <div>
            <b>Điểm sẵn sàng</b>
            <dl className="kv" style={{ marginTop: 6 }}>
              {parts.map(([k, v]) => (<Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>))}
            </dl>
          </div>
        </div>
      </div>

      <div>
        <b>Kế hoạch bán</b>
        <p style={{ margin: "4px 0 0" }}>{plan.exit}</p>
        {plan.cause && <p className="muted" style={{ margin: "4px 0 0" }}>
          Nhân: {plan.cause.cols} cột P&F (ô {num(plan.cause.box, 2)}, đảo 3 ô) → Quả ≈ {price(plan.cause.width, unit)}.
        </p>}
        {plan.notes.length > 0 && <ul className="sig" style={{ marginTop: 6 }}>{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
        Ước lượng tự động theo Wyckoff, không phải khuyến nghị đầu tư. Giá {price(c, unit)} tại phiên gần nhất.
      </p>
    </section>
  );
}
