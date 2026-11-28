import { num, price, type Plan, type ScenarioStat } from "@/lib/api";

const LIGHT: Record<string, string> = { green: "đèn xanh", yellow: "đèn vàng", red: "đèn đỏ", "*": "mọi đèn" };
const FEW = 30;

/** Tỷ lệ 3 kịch bản (chạm T1 / hết thời gian / cắt lỗ) của các lệnh backtest đã khớp cùng loại kế hoạch, ưu tiên cùng
 *  màu đèn với phiên đang xem, kèm R TB. Số liệu từ app.backtest (bảng scenario_stats, cùng nguồn với backtest_stats). */
export default function ScenarioOdds({ plan, light, rows }: { plan: Plan; light: string | null; rows: ScenarioStat[] }) {
  if (!rows.length || !plan.stop || !plan.targets.length || rows.every((r) => r.avg_r == null)) return null;   // bản cũ: ẩn
  const by = Object.fromEntries(rows.map((r) => [r.light, r]));
  const cur = light && by[light]?.n >= FEW ? by[light] : by["*"];
  if (!cur) return null;
  const others = ["green", "yellow", "red", "*"].filter((l) => by[l] && by[l] !== cur).map((l) => by[l]);
  const t1 = plan.targets[0].price;
  const sc = [
    { k: "up", v: cur.up, color: "var(--up)", label: `Chạm T1 ${price(t1)} trước`, days: cur.up_days },
    { k: "flat", v: cur.flat, color: "var(--muted)", label: `Hết ${cur.horizon} phiên chưa tới T1`, days: null },
    { k: "down", v: cur.down, color: "var(--down)", label: `Cắt lỗ ${price(plan.stop)} trước`, days: cur.down_days },
  ];
  const top = sc.reduce((a, b) => (b.v > a.v ? b : a));

  const bar = (r: ScenarioStat, h: number) => (
    <div style={{ display: "flex", height: h, borderRadius: 4, overflow: "hidden", background: "var(--grid)" }}>
      <div style={{ width: `${r.up}%`, background: "var(--up)" }} />
      <div style={{ width: `${r.flat}%`, background: "var(--muted)", opacity: 0.45 }} />
      <div style={{ width: `${r.down}%`, background: "var(--down)" }} />
    </div>
  );

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>Lịch sử: lệnh “{cur.plan}” đã khớp đi theo kịch bản nào?</b>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {num(cur.n)} lệnh lúc {LIGHT[cur.light] ?? cur.light} · {cur.period}
          {cur.light === "*" && light ? ` (${LIGHT[light] ?? light} chưa đủ mẫu)` : ""}</span>
      </div>
      {bar(cur, 16)}
      <div className="row" style={{ gap: 16 }}>
        {sc.map((s) => (
          <span key={s.k} style={{ fontWeight: s === top ? 700 : 400 }}>
            <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: s.color,
              opacity: s.k === "flat" ? 0.45 : 1, marginRight: 6 }} />
            {s.label}: <span className={s.k === "up" ? "up" : s.k === "down" ? "down" : ""}>{num(s.v)}%</span>
            {s.days ? <span className="muted"> (~{num(s.days)} phiên)</span> : null}
          </span>
        ))}
      </div>
      <p style={{ margin: 0 }}>→ Khả năng cao nhất: <b>{top.label[0].toLowerCase() + top.label.slice(1)}</b> ({num(top.v)}%).
        {cur.avg_r != null && <> Bình quân mỗi lệnh <b className={cur.avg_r >= 0 ? "up" : "down"}>{cur.avg_r > 0 ? "+" : ""}{num(cur.avg_r, 2)}R</b>
          {cur.ci_lo != null && cur.ci_hi != null && <span className="muted"> (KTC95% {num(cur.ci_lo, 2)}…{num(cur.ci_hi, 2)}
            {cur.ci_lo < 0 && cur.ci_hi > 0 ? ": chưa chắc có lợi thế" : ""})</span>}.</>}</p>
      {others.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "72px minmax(60px, 1fr) auto", gap: "4px 10px", alignItems: "center", fontSize: 12.5 }}>
          {others.map((r) => [
            <span key={r.light + "l"} className="muted">{LIGHT[r.light] ?? r.light}</span>,
            <span key={r.light + "b"}>{bar(r, 8)}</span>,
            <span key={r.light + "n"} className="muted">
              {num(r.up)}% / {num(r.flat)}% / {num(r.down)}% · {num(r.n)} lệnh{r.n < FEW ? " (ít)" : ""}
              {r.avg_r != null ? ` · ${r.avg_r > 0 ? "+" : ""}${num(r.avg_r, 2)}R` : ""}</span>,
          ])}
        </div>
      )}
      <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
        Đếm trên các lệnh backtest {cur.period} đã khớp vùng vào và đã đóng theo luật bán của app (cùng số với dòng thống kê
        dưới biểu đồ): chạm T1, cắt lỗ khi chưa tới T1, hay hết {cur.horizon} phiên chưa tới T1. R đã trừ phí, thuế, trượt giá.
        Là tần suất trong quá khứ, không phải dự báo.
      </p>
    </div>
  );
}
