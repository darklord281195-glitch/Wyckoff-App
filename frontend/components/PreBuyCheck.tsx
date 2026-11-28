"use client";
import { useCallback, useEffect, useState } from "react";
import { api, day, num, pct, price, type BuyCheck } from "@/lib/api";

const TONE: Record<BuyCheck["verdict"], { bg: string; fg: string }> = {
  buy: { bg: "rgba(20, 150, 106, .12)", fg: "var(--up)" },
  half: { bg: "rgba(20, 150, 106, .12)", fg: "var(--up)" },
  red: { bg: "rgba(210, 69, 59, .12)", fg: "var(--down)" },
  wait: { bg: "rgba(214, 158, 46, .15)", fg: "var(--warn)" },
  no: { bg: "var(--grid)", fg: "var(--fg)" },
};
const LIGHT_VN: Record<string, string> = { green: "xanh", yellow: "vàng", red: "đỏ" };

/** Giờ Việt Nam đang trong phiên (thứ 2–6, 9:00–15:00): tự kiểm tra lại mỗi phút. */
const inSession = () => {
  const t = new Date(Date.now() + 7 * 3600e3);
  const m = t.getUTCHours() * 60 + t.getUTCMinutes();
  return t.getUTCDay() >= 1 && t.getUTCDay() <= 5 && m >= 540 && m <= 900;
};

/** Lỗi từ api(): "Error: 502 {"detail":"..."}" -> chỉ lấy phần detail. */
const errText = (e: unknown) => {
  const s = String(e).replace(/^Error: \d+ /, "");
  try { return JSON.parse(s).detail ?? s; } catch { return s; }
};

/** Bảng kiểm tra trước khi mua (dùng lúc 14h15–14h29): từng điều kiện "Kịch bản mua đẹp" theo nến đang chạy, kết luận,
 *  khối lượng gợi ý theo vốn / % rủi ro / đèn. Cùng luật với sổ lệnh thử nghiệm (intraday.checklist). */
export default function PreBuyCheck({ sym }: { sym: string }) {
  const [d, setD] = useState<BuyCheck | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    setBusy(true);
    api<BuyCheck>(`/api/symbols/${sym}/check`).then((x) => { setD(x); setErr(null); })
      .catch((e) => setErr(errText(e))).finally(() => setBusy(false));
  }, [sym]);
  useEffect(() => {
    setD(null); load();
    const id = setInterval(() => { if (inSession() && document.visibilityState === "visible") load(); }, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const tone = d ? TONE[d.verdict] : TONE.no;
  const s = d?.size;
  const friday = d ? new Date(d.d + "T00:00:00Z").getUTCDay() === 5 : false;
  return (
    <section className="card" style={{ display: "grid", gap: 10 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Kiểm tra trước khi mua</h2>
        <span className="row muted" style={{ gap: 8, fontSize: 12.5 }}>
          {d && <span>{d.live ? "phiên đang chạy" : `phiên ${day(d.d)}`} · lúc {d.at}</span>}
          <button className="btn" onClick={load} disabled={busy}>{busy ? "Đang kiểm tra…" : "Kiểm tra lại"}</button>
        </span>
      </div>
      {err && <p className="down" style={{ margin: 0 }}>Không kiểm tra được: {err}</p>}
      {!d && !err && <p className="muted" style={{ margin: 0 }}>Đang lấy giá hôm nay…</p>}
      {d && <>
        <div style={{ padding: "10px 12px", borderRadius: 8, background: tone.bg, color: tone.fg, fontWeight: 600 }}>{d.text}</div>
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
          {d.items.map((x) => (
            <li key={x.key} style={{ display: "grid", gridTemplateColumns: "18px 1fr", gap: 8 }}>
              <b className={x.ok === true ? "up" : x.ok === false && !x.advisory ? "down" : "muted"}
                style={x.ok === false && x.advisory ? { color: "var(--warn)" } : undefined}
                aria-label={x.ok === true ? "đạt" : x.ok === false ? (x.advisory ? "lưu ý" : "chưa đạt") : "không áp dụng"}>
                {x.ok === true ? "✓" : x.ok === false ? (x.advisory ? "⚠" : "✗") : "–"}</b>
              <span><span style={{ fontWeight: x.ok === false ? 600 : 400 }}>{x.label}</span>
                {x.advisory && <span className="muted" style={{ fontSize: 12 }}> (tham khảo)</span>}
                <span className="muted" style={{ fontSize: 12.5 }}> · {x.detail}</span></span>
            </li>
          ))}
        </ul>
        <p style={{ margin: 0 }}>
          Giá {price(d.price)} <span className={(d.chg ?? 0) >= 0 ? "up" : "down"}>{pct(d.chg, 2)}</span> · đèn {LIGHT_VN[d.light] ?? d.light}
          {d.stop != null && <> · cắt lỗ {price(d.stop)}</>}{d.t1 != null && <> · T1 {price(d.t1)}</>}
        </p>
        {s && (s.factor === 0
          ? <p style={{ margin: 0 }}>Khối lượng: <b>0 cp</b>. Đèn đỏ: hệ số rủi ro 0, không mở lệnh mới.</p>
          : <p style={{ margin: 0 }}>
              Khối lượng: bước 1 <b>{num(s.step1)} cp</b> (~{num(s.step1 * d.price / 1000, 1)} triệu), đủ vị thế {num(s.shares)} cp
              {" "}nếu các bước sau đạt · rủi ro tối đa {num(s.risk_money / 1e6, 2)} triệu (vốn × % rủi ro{s.factor < 1 ? ` × ${num(s.factor, 1)} theo đèn` : ""})
              {" "}· cắt lỗ {pct(s.stop_pct)} · tổng rủi ro danh mục sau khi mua đủ{" "}
              <b className={s.heat_after > s.max_heat ? "down" : ""}>{num(s.heat_after, 1)}%</b> / ngưỡng {num(s.max_heat, 1)}%
              {d.positions.n >= d.positions.max_pos && <span className="down"> · đã giữ {d.positions.n}/{d.positions.max_pos} lệnh</span>}
            </p>)}
        <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
          {d.note} Hàng về chiều T+2: bị đạp ngay thì lỗ thực tế có thể gấp đôi khoảng cắt lỗ{friday ? "; mua thứ 6 còn thêm rủi ro qua cuối tuần" : ""}.
          {" "}Cùng luật với sổ lệnh thử nghiệm (app tự mua 14h10–14h29).
        </p>
      </>}
    </section>
  );
}
