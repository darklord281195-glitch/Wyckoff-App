"use client";
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, day, fullDate, num, pct, price, type RankBt, type TopItem, type TopResp, type TopRow } from "@/lib/api";

/** 3 thành phần tính điểm (backend core/rank.py FACTORS); luôn đi kèm số nên không phụ thuộc màu */
const FACTORS = [
  { k: "dry", label: "Cung cạn", color: "#3b5bdb" },
  { k: "vol", label: "Biến động thấp", color: "#0ea5e9" },
  { k: "ready", label: "Sẵn sàng", color: "#e0a72e" },
] as const;
/** 3 mục cũ: chỉ hiện tham khảo trong phần chi tiết */
const PILLARS = [
  { k: "wyckoff", label: "Wyckoff", color: "#3b5bdb" },
  { k: "tech", label: "KT & CB", color: "#0ea5e9" },
  { k: "flow", label: "Dòng tiền", color: "#e0a72e" },
] as const;
const TONE: Record<TopItem["tone"], string> = { good: "var(--up)", warn: "var(--warn)", bad: "var(--down)", info: "var(--muted)" };
const LIGHT_VN: Record<string, string> = { green: "Đèn xanh", yellow: "Đèn vàng", red: "Đèn đỏ" };
const N_KEY = "wyckoff.top.n";                                   // localStorage: số mã chọn xem (10/20/30)
const F_KEY = "wyckoff.top.formula";                             // localStorage: công thức đang xem (new / old)
type Formula = "new" | "old";

const TIPS: Record<string, string> = {
  "Hạng": "Thứ hạng theo điểm. ▲▼ = lên/xuống bao nhiêu bậc so với phiên đang so sánh; 🆕 = trước đó chưa nằm trong top.",
  "Mã": "Mã cổ phiếu; dòng nhỏ là ngành ICB và sàn. Bấm dòng để xem chi tiết điểm, bấm mã để mở trang mã.",
  "Điểm": "Điểm % = trung bình 3 thành phần, mỗi thành phần là % số mã trong nhóm được xếp mà mã này hơn. Thanh màu: phần đóng góp của Cung cạn · Biến động thấp · Sẵn sàng.",
  "Cung cạn": "KL TB 10 phiên so với TB 60 phiên: càng thấp càng tốt (cạn cung, tinh thần Wyckoff). Số = mã này cạn hơn bao nhiêu % số mã.",
  "Biến động thấp": "Độ dao động giá ngày trong 20 phiên: càng thấp càng tốt. Số = mã này ít dao động hơn bao nhiêu % số mã.",
  "Sẵn sàng": "Điểm sẵn sàng của kế hoạch Wyckoff (0–100). Số = cao hơn bao nhiêu % số mã; chưa có kế hoạch tính 50.",
  "Trong top": "Số phiên mã nằm trong top trong tối đa 20 phiên đã lưu gần nhất.",
  "Wyckoff": "Công thức cũ, mục 1 (0–100): pha Wyckoff, điểm sẵn sàng, giá so với vùng vào, lời/lỗ, dư địa tới mục tiêu; trừ điểm khi có chuỗi đỉnh hạ hoặc vùng phân phối.",
  "KT & CB": "Công thức cũ, mục 2 (0–100): RSI 14, MACD, MCDX (tay to), Ichimoku và BCTC, mỗi phần tối đa 20.",
  "Dòng tiền": "Công thức cũ, mục 3 (0–100): khối ngoại (50) và tự doanh (50) mua ròng 20 phiên so với giá trị giao dịch 20 phiên.",
  "Pha": "Pha Wyckoff hiện tại (như trang Tổng quan).",
  "Vùng vào": "Vùng giá mua theo kế hoạch giao dịch. 🎯 = giá đang nằm trong vùng.",
  "Cắt lỗ": "Giá cắt lỗ của kế hoạch.",
  "Lời/lỗ": "Lời/lỗ tới mục tiêu chính của kế hoạch.",
  "Nổi bật": "Tối đa 3 điểm mạnh nhất; ⚠ = số điểm yếu / cảnh báo (rê chuột để xem).",
};

function Bar({ v, color, w = 64 }: { v: number; color: string; w?: number }) {
  return <div className="meter" style={{ width: w, height: 6 }}><div style={{ width: `${Math.max(0, Math.min(100, v))}%`, background: color }} /></div>;
}

/** thanh chồng 3 màu: mỗi đoạn = 1/3 × phần trăm của thành phần, tổng chiều dài = điểm % */
function Stack({ r, old }: { r: TopRow; old: boolean }) {
  if (old) return (
    <div className="meter" style={{ width: 80, height: 7, display: "flex" }}
      title={PILLARS.map((p) => `${p.label} ${r.pillars[p.k].score}`).join(" · ")}>
      {PILLARS.map((p) => <div key={p.k} style={{ width: `${r.pillars[p.k].score / 3}%`, background: p.color, borderRadius: 0 }} />)}
    </div>
  );
  return (
    <div className="meter" style={{ width: 80, height: 7, display: "flex" }}
      title={FACTORS.map((f) => `${f.label} ${num(r.parts?.[f.k] ?? 0, 0)}`).join(" · ")}>
      {FACTORS.map((f) => <div key={f.k} style={{ width: `${(r.parts?.[f.k] ?? 0) / 3}%`, background: f.color, borderRadius: 0 }} />)}
    </div>
  );
}

function Move({ r, pos }: { r: TopRow; pos: number }) {
  if (r.new) return <span title={r.prev_pos ? `trước đó #${r.prev_pos}` : "trước đó chưa có trong bảng"}> 🆕</span>;
  if (r.prev_pos == null) return null;
  const d = r.prev_pos - pos;
  return d === 0 ? <span className="muted" style={{ fontSize: 11.5 }}> =</span>
    : <span className={d > 0 ? "up" : "down"} style={{ fontSize: 11.5 }} title={`trước đó #${r.prev_pos}`}> {d > 0 ? "▲" : "▼"}{Math.abs(d)}</span>;
}

function Detail({ r, at, old }: { r: TopRow; at: string; old: boolean }) {
  return (
    <div style={{ display: "grid", gap: 10, padding: "6px 2px", whiteSpace: "normal", position: "sticky", left: 0,
      maxWidth: "min(1240px, calc(100vw - 90px))" }}>
      {r.factors.length > 0 && <div style={{ display: "grid", gap: 6, order: old ? 3 : 0, opacity: old ? .85 : 1 }}>
        <div style={{ fontWeight: 600 }} className={old ? "muted" : ""}>{old ? `Tham khảo – công thức mới: ${r.parts ? Math.round((r.parts.dry + r.parts.vol + r.parts.ready) / 3) : "–"}%`
          : `Điểm ${r.total}% = trung bình 3 thành phần`}</div>
        {r.factors.map((x, i) => (
          <div key={x.key} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, fontSize: 13, lineHeight: 1.45 }}>
            <span><b style={{ fontWeight: 600, color: FACTORS[i]?.color }}>■ {x.label}</b> <span style={{ color: TONE[x.tone] }}>· {x.text}</span></span>
            <span className="mono" style={{ color: TONE[x.tone], fontSize: 12.5 }}>{num(x.pts, 0)}/100</span>
          </div>
        ))}
      </div>}
      <div className={old ? "" : "muted"} style={{ fontSize: old ? 14 : 12.5, fontWeight: 600, order: old ? 1 : 0 }}>
        {old ? `Điểm ${r.total}% = trung bình 3 mục (công thức cũ)` : `Tham khảo – công thức cũ 3 mục: ${r.ref_total}%`}</div>
      <div style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", opacity: old ? 1 : .85, order: old ? 2 : 0 }}>
        {PILLARS.map((p) => (
          <div key={p.k} style={{ display: "grid", gap: 6, alignContent: "start" }}>
            <div style={{ fontWeight: 600 }}><span style={{ color: p.color }}>■</span> {p.label} · {r.pillars[p.k].score}/100</div>
            {r.pillars[p.k].items.map((x) => (
              <div key={x.key} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, fontSize: 13, lineHeight: 1.45 }}>
                <span><b style={{ fontWeight: 600 }}>{x.label}</b> <span style={{ color: TONE[x.tone] }}>· {x.text}</span></span>
                <span className="mono" style={{ color: TONE[x.tone], fontSize: 12.5 }}>
                  {x.max ? `${num(x.pts, x.pts % 1 ? 1 : 0)}/${x.max}` : x.pts ? num(x.pts) : ""}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
      {r.warnings.length > 0 && <div style={{ fontSize: 13, color: "var(--down)", order: 4 }}>⚠ {r.warnings.map((w) => w.text).join(" · ")}</div>}
      <div className="row" style={{ gap: 14, fontSize: 13, order: 5 }}>
        {r.target && <span className="muted">Mục tiêu chính {r.target.k} {price(r.target.price)} ({pct(r.target.upside)})</span>}
        {!r.eligible && <span className="muted">Chưa có điểm mua: chờ nhịp lùi / vùng vào theo kế hoạch</span>}
        {r.pct_rank != null && <span className="muted">Điểm cao hơn {r.pct_rank}% số mã {old ? "có điểm mua" : "được xếp"}</span>}
        <Link href={`/symbol/${r.sym}${at}`} style={{ color: "var(--accent)", fontWeight: 600 }}>Mở trang mã →</Link>
      </div>
    </div>
  );
}

function summary(v: RankBt[]): string {
  const a = v.find((x) => x.period === "2019–23"), b = v.find((x) => x.period === "2024–26"), all = v.find((x) => x.period === "Tất cả");
  if (!a || !b) return "Chưa đủ hai giai đoạn để kết luận.";
  const n = a.top_n, win = (x: RankBt) => (x.top_ret ?? -99) > (x.liq_ret ?? 99);
  const ex = (x: RankBt) => pct((x.top_ret ?? 0) - (x.liq_ret ?? 0), 2);
  const head = win(a) && win(b) ? `Top ${n} có lợi nhuận cao hơn TB mọi mã đủ thanh khoản ở cả hai giai đoạn (${ex(a)} và ${ex(b)} mỗi ${a.hold} phiên, chưa trừ phí).`
    : win(a) || win(b) ? `Chưa có lợi thế ổn định: top ${n} chỉ hơn TB thị trường ở giai đoạn ${win(a) ? "2019–23" : "2024–26"}.`
    : `Chưa có lợi thế: top ${n} không hơn TB thị trường ở giai đoạn nào.`;
  const ic = all?.ic;
  const tail = ic == null ? "" : Math.abs(ic) < 0.03 ? " Điểm gần như không tương quan với lợi nhuận 20 phiên sau (IC ≈ 0)."
    : ic > 0 ? ` IC tổng ${num(ic, 3)}: điểm cao có xu hướng lời hơn.` : ` IC tổng ${num(ic, 3)}: điểm cao không đi kèm lợi nhuận cao hơn.`;
  return head + tail;
}

export default function TopPage() {
  const router = useRouter();
  const [data, setData] = useState<TopResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [dates, setDates] = useState<string[]>([]);
  const [sel, setSel] = useState<string | null>(null);              // null = chưa đọc URL; "" = phiên mới nhất
  const [n, setN] = useState(10);
  const [vs, setVs] = useState<"prev" | "week">("prev");
  const [minLiq, setMinLiq] = useState(10);
  const [liqIn, setLiqIn] = useState("10");
  const [onlyBuy, setOnlyBuy] = useState(false);
  const [formula, setFormula] = useState<Formula>("new");
  const [open, setOpen] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setSel(new URLSearchParams(window.location.search).get("date") ?? "");
    try {
      const v = Number(localStorage.getItem(N_KEY)); if ([10, 20, 30].includes(v)) setN(v);
      if (localStorage.getItem(F_KEY) === "old") { setFormula("old"); setOnlyBuy(true); }
    } catch { /* chế độ riêng tư */ }
    api<string[]>("/api/scan/dates").then(setDates).catch(() => {});
  }, []);
  useEffect(() => {                                               // gõ ô GT: chờ 400 ms rồi mới tải
    const t = setTimeout(() => { const v = Number(liqIn); if (liqIn !== "" && v >= 0) setMinLiq(v); }, 400);
    return () => clearTimeout(t);
  }, [liqIn]);
  useEffect(() => {
    if (sel == null) return;
    setLoading(true);
    const q = new URLSearchParams({ n: String(n), vs, min_liq: String(minLiq), all: String(!onlyBuy), formula });
    if (sel) q.set("date", sel);
    api<TopResp>("/api/top?" + q).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, [sel, n, vs, minLiq, onlyBuy, formula]);

  /** đổi công thức: mỗi công thức có bộ lọc mặc định riêng (mới: mọi mã; cũ: chỉ mã có điểm mua, như trước) */
  const pickF = (f: Formula) => {
    setFormula(f); setOnlyBuy(f === "old"); setOpen(null);
    try { localStorage.setItem(F_KEY, f); } catch { /* bỏ qua */ }
  };
  const pickN = (v: number) => { setN(v); try { localStorage.setItem(N_KEY, String(v)); } catch { /* bỏ qua */ } };
  const pick = (d: string) => {
    const v = d === dates[0] ? "" : d;
    setSel(v); router.replace(v ? "/top?date=" + v : "/top", { scroll: false });
  };
  const past = !!sel && sel !== dates[0];
  const at = past ? "?at=" + sel : "";
  const th = (label: string, cls?: string) => <th className={cls} title={TIPS[label]}><span className="tip">{label}</span></th>;

  if (err) return <div className="card">Không tải được Top tiềm năng ({err}).</div>;
  const d = data;
  const old = d?.formula === "old";
  const COLS3 = old ? PILLARS : FACTORS;
  const showIn = !!d && d.rows.some((r) => r.in_top_of >= 2);
  const cols = showIn ? 12 : 11;
  const v = d?.validation;

  return (
    <>
      <section className="card hero">
        <div style={{ display: "grid", gap: 6, minWidth: 0 }}>
          <div className="row" style={{ gap: 10 }}>
            <h1 style={{ margin: 0, fontSize: 22 }}>Top {n} tiềm năng{d ? ` · phiên ${day(d.date)}` : ""}</h1>
            {d?.light && d.light !== "?" && <span className={`badge ${d.light}`}><span className={`light ${d.light}`} style={{ width: 8, height: 8, boxShadow: "none" }} />
              {LIGHT_VN[d.light]}</span>}
          </div>
          <div className="muted" style={{ fontSize: 13.5 }}>
            {old ? <>Công thức cũ (chạy song song để so): điểm = trung bình 3 mục <b style={{ color: PILLARS[0].color }}>Wyckoff</b> · <b style={{ color: PILLARS[1].color }}>Kỹ thuật & Cơ bản</b> · <b style={{ color: PILLARS[2].color }}>Dòng tiền</b>.{" "}</> : <>
            Điểm = trung bình 3 thành phần: <b style={{ color: FACTORS[0].color }}>Cung cạn</b> · <b style={{ color: FACTORS[1].color }}>Biến động thấp</b> · <b style={{ color: FACTORS[2].color }}>Điểm sẵn sàng</b>,
            {" "}xếp trong các mã đủ thanh khoản trừ nhóm {d ? d.exclude.join(", ") : "B/C, SOS hỏng, dưới hỗ trợ"}.
            </>}{" "}Tự tính lại sau mỗi phiên (sau lần quét 15:30). Hợp để chọn mã nắm 1–3 tháng.
          </div>
        </div>
        <div className="row">
          <label className="muted">Phiên{" "}
            <select id="session" className="btn" value={d?.date ?? ""} onChange={(e) => pick(e.target.value)} disabled={dates.length < 2}>
              {!d && <option value="">–</option>}
              {dates.map((x, i) => <option key={x} value={x}>{fullDate(x)}{i === 0 ? " (mới nhất)" : ""}</option>)}
            </select></label>
        </div>
      </section>

      {d?.light === "red" && <div className="notice" style={{ background: "rgba(224, 72, 63, .1)" }}>
        🔴 Đèn đỏ: luật app không mở lệnh mới. Danh sách chỉ để theo dõi, chờ đèn chuyển vàng/xanh.</div>}
      {d?.light === "yellow" && <div className="notice" style={{ background: "rgba(224, 167, 46, .14)" }}>
        🟡 Đèn vàng: luật app ẩn tín hiệu LPS và D sớm (backtest kỳ vọng âm ở đèn vàng); các mã đó có cảnh báo ⚠.</div>}
      {past && d && <div className="notice">Đang xem phiên cũ {fullDate(d.date)}: điểm tính bằng dữ liệu tới phiên này.
        <button className="btn" onClick={() => pick(dates[0])}>Về phiên mới nhất</button></div>}

      <section className="card" style={{ display: "grid", gap: 12, alignContent: "start" }}>
        <div className="row" style={{ gap: 10 }}>
          <div className="tabs" role="group" aria-label="Công thức">
            <span className="muted" style={{ padding: "5px 4px 5px 8px", fontSize: 13 }}>Công thức:</span>
            <button className={formula === "new" ? "on" : ""} onClick={() => pickF("new")}
              title="Cung cạn · biến động thấp · điểm sẵn sàng (chọn theo kiểm chứng lịch sử)">Mới</button>
            <button className={formula === "old" ? "on" : ""} onClick={() => pickF("old")}
              title="3 mục Wyckoff · Kỹ thuật & Cơ bản · Dòng tiền, 1/3 mỗi mục (công thức ban đầu)">Cũ (3 mục)</button>
          </div>
          <div className="tabs" role="group" aria-label="Số mã">
            {[10, 20, 30].map((x) => <button key={x} className={n === x ? "on" : ""} onClick={() => pickN(x)}>Top {x}</button>)}
          </div>
          <div className="tabs" role="group" aria-label="So với">
            <span className="muted" style={{ padding: "5px 4px 5px 8px", fontSize: 13 }}>So với:</span>
            <button className={vs === "prev" ? "on" : ""} onClick={() => setVs("prev")}>Phiên trước</button>
            <button className={vs === "week" ? "on" : ""} onClick={() => setVs("week")}>1 tuần trước</button>
          </div>
          <label className="muted" style={{ whiteSpace: "nowrap" }}>GT ≥ <input id="minliq" type="number" min={0} value={liqIn}
            onChange={(e) => setLiqIn(e.target.value)} style={{ width: 70 }} /> tỷ</label>
          <label className="muted" style={{ whiteSpace: "nowrap", display: "inline-flex", gap: 6, alignItems: "center" }}>
            <input id="onlybuy" type="checkbox" checked={onlyBuy} onChange={(e) => setOnlyBuy(e.target.checked)} /> Chỉ mã có điểm mua</label>
          {loading && <span className="muted" style={{ fontSize: 12.5 }}>Đang tải…</span>}
        </div>
        <div className="tbl">
          <table className="right compact">
            <thead>
              <tr>
                {th("Hạng")}{th("Mã")}{th("Điểm")}{COLS3.map((c) => <Fragment key={c.k}>{th(c.label, "n")}</Fragment>)}
                {showIn && th("Trong top", "n")}{th("Pha")}{th("Vùng vào", "n")}{th("Cắt lỗ", "n")}{th("Lời/lỗ", "n")}{th("Nổi bật")}
              </tr>
            </thead>
            <tbody>
              {d?.rows.map((r, i) => (
                <Fragment key={r.sym}>
                  <tr className={open === r.sym ? "on" : ""} style={{ cursor: "pointer" }} onClick={() => setOpen(open === r.sym ? null : r.sym)}
                    aria-expanded={open === r.sym}>
                    <td style={{ fontWeight: 600 }}>#{i + 1}<Move r={r} pos={i + 1} /></td>
                    <td title={r.name ?? ""}>
                      <Link href={`/symbol/${r.sym}${at}`} onClick={(e) => e.stopPropagation()}><b>{r.sym}</b></Link>
                      <div className="muted" style={{ fontSize: 11.5, maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis" }}>
                        {[r.icb_name, r.floor].filter(Boolean).join(" · ")}</div></td>
                    <td><div style={{ display: "grid", gap: 4 }}>
                      <b className="mono" style={{ fontSize: 15 }}>{r.total}%</b><Stack r={r} old={old} /></div></td>
                    {old ? PILLARS.map((p) => (
                      <td key={p.k} className="n"><div style={{ display: "grid", gap: 4, justifyItems: "end" }}>
                        {r.pillars[p.k].score}<Bar v={r.pillars[p.k].score} color={p.color} w={48} /></div></td>
                    )) : FACTORS.map((f, k) => (
                      <td key={f.k} className="n" title={r.factors[k]?.text}><div style={{ display: "grid", gap: 4, justifyItems: "end" }}>
                        {num(r.parts?.[f.k] ?? 0, 0)}<Bar v={r.parts?.[f.k] ?? 0} color={f.color} w={48} /></div></td>
                    ))}
                    {showIn && <td className="n">{r.in_top}/{r.in_top_of} <span className="muted" style={{ fontFamily: "var(--font)", fontSize: 11.5 }}>phiên</span></td>}
                    <td><span className={`pill ${r.stage}`}>{r.tag}</span></td>
                    <td className="n" title={r.plan_kind ?? ""}>{r.entry_lo ? `${price(r.entry_lo)}–${price(r.entry_hi)}`
                      : <span className="muted" style={{ fontFamily: "var(--font)", fontSize: 12 }}>chưa có điểm mua</span>}{r.in_zone ? " 🎯" : ""}</td>
                    <td className="n down">{price(r.stop)}</td>
                    <td className={`n ${(r.rr ?? 0) >= 2 ? "up" : ""}`}>{r.rr != null ? num(r.rr, 1) : "–"}</td>
                    <td style={{ whiteSpace: "normal", minWidth: 190 }}>
                      <div className="row" style={{ gap: 4 }}>
                        {r.highlights.map((h) => <span key={h.key} className="pill" style={{ background: "rgba(15, 157, 107, .1)", color: "var(--up)", fontWeight: 500, fontSize: 11.5 }}
                          title={h.text}>{h.label}</span>)}
                        {r.warnings.length > 0 && <span className="pill" style={{ background: "rgba(214, 69, 61, .1)", color: "var(--down)", fontWeight: 500, fontSize: 11.5 }}
                          title={r.warnings.map((w) => `${w.label}: ${w.text}`).join("\n")}>⚠ {r.warnings.length}</span>}
                      </div></td>
                  </tr>
                  {open === r.sym && <tr className="on"><td colSpan={cols}><Detail r={r} at={at} old={old} /></td></tr>}
                </Fragment>
              ))}
              {d && d.rows.length === 0 && <tr><td colSpan={cols} className="muted">Không có mã nào thỏa bộ lọc.</td></tr>}
            </tbody>
          </table>
        </div>
        {d && <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
          {old ? `${d.n_liquid} mã GT ≥ ${num(d.min_liq)} tỷ` : `${d.n_liquid} mã GT ≥ ${num(d.min_liq)} tỷ, ${d.n_pool} mã được xếp (trong đó ${d.n_eligible} mã có điểm mua)`}
          {" "}· bấm một dòng để xem chi tiết điểm
          {d.compare.date ? ` · so với phiên ${day(d.compare.date)}` : " · chưa có phiên trước để so sánh"}</p>}
        {d && <p style={{ margin: 0, fontSize: 13.5 }}><b>Cả hai công thức cùng chọn:</b>{" "}
          {d.both.length ? d.both.map((s, i) => <span key={s}>{i ? " · " : ""}<Link href={`/symbol/${s}${at}`}><b>{s}</b></Link></span>)
            : <span className="muted">không có mã nào chung trong top {n}</span>}</p>}
        {d && d.compare.date && d.dropped.length > 0 && <p style={{ margin: 0, fontSize: 13.5 }}>
          <b>Rời top so với {day(d.compare.date)}:</b>{" "}
          {d.dropped.map((x, i) => <span key={x.sym}>{i ? " · " : ""}<Link href={`/symbol/${x.sym}${at}`}><b>{x.sym}</b></Link>{" "}
            <span className="muted">({x.reason ?? `nay #${x.pos}, ${x.total}%`})</span></span>)}</p>}
      </section>

      <section className="card" style={{ display: "grid", gap: 10 }}>
        <h2 style={{ margin: 0 }}>Kiểm chứng lịch sử · công thức {old ? "cũ (3 mục)" : "mới"}</h2>
        {!v ? <p className="muted" style={{ margin: 0 }}>Chưa chạy kiểm chứng: <code>python -m app.rank_bt</code> (trong thư mục backend).</p> : <>
          <p style={{ margin: 0 }}>{summary(v.rows)}</p>
          <div className="tbl">
            <table className="right" style={{ minWidth: 820 }}>
              <thead><tr>
                <th>Giai đoạn</th><th className="n">Số tháng</th>
                <th className="n" title="Lợi nhuận TB 20 phiên của top N đầu mỗi tháng (mua giá mở cửa phiên sau)"><span className="tip">Top {v.rows[0]?.top_n}</span></th>
                <th className="n" title={old ? "Lợi nhuận TB của mọi mã có điểm mua (nhóm công thức cũ xếp hạng)" : "Lợi nhuận TB của nhóm được xếp (mã đủ thanh khoản trừ B/C, SOS hỏng, dưới hỗ trợ)"}>
                  <span className="tip">{old ? "Có điểm mua" : "Nhóm được xếp"}</span></th>
                <th className="n" title="Lợi nhuận TB của mọi mã GT ≥ 10 tỷ"><span className="tip">Đủ thanh khoản</span></th>
                <th className="n">VNINDEX</th>
                <th className="n" title="% số tháng top thắng TB mọi mã đủ thanh khoản"><span className="tip">Top thắng</span></th>
                <th className="n" title="% lượt chọn của top có lời sau 20 phiên"><span className="tip">Lượt có lời</span></th>
                <th className="n" title="IC: tương quan hạng (Spearman) giữa điểm và lợi nhuận 20 phiên sau trong nhóm được xếp, TB các tháng. > 0,05 là có ích, ≈ 0 là không dự báo được."><span className="tip">IC tổng</span></th>
                {old ? <><th className="n">IC Wyckoff</th><th className="n">IC KT&CB</th><th className="n">IC dòng tiền</th></>
                  : <><th className="n">IC cung cạn</th><th className="n">IC biến động</th><th className="n">IC sẵn sàng</th></>}
              </tr></thead>
              <tbody>
                {v.rows.map((x) => (
                  <tr key={x.period}>
                    <td style={{ fontWeight: 600 }}>{x.period}</td><td className="n">{x.months}</td>
                    <td className={`n ${(x.top_ret ?? 0) > (x.liq_ret ?? 0) ? "up" : "down"}`} style={{ fontWeight: 600 }}>{pct(x.top_ret, 2)}</td>
                    <td className="n">{pct(x.elig_ret, 2)}</td><td className="n">{pct(x.liq_ret, 2)}</td><td className="n">{pct(x.vni_ret, 2)}</td>
                    <td className="n">{num(x.beat_pct, 0)}%</td><td className="n">{num(x.top_win, 0)}%</td>
                    <td className="n">{num(x.ic, 3)}</td><td className="n">{num(x.ic_w, 3)}</td><td className="n">{num(x.ic_t, 3)}</td><td className="n">{num(x.ic_f, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
            Cập nhật {fullDate(v.updated)} · tự chạy lại mỗi thứ 6 · lợi nhuận %/{v.rows[0]?.hold} phiên, chưa trừ phí · chỉ có mã đang niêm yết
            (kết quả có thể đẹp hơn thực tế) · phí + thuế + trượt giá khoảng 1% mỗi lần mua–bán, nên không đổi danh sách liên tục.</p>
        </>}
      </section>

      <details className="card">
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>Cách chấm điểm</summary>
        <div style={{ display: "grid", gap: 8, marginTop: 10, fontSize: 14, lineHeight: 1.6 }}>
          <p style={{ margin: 0 }}><b>Điểm xếp hạng (từ 28/11/2026).</b> Mỗi phiên, các mã đủ thanh khoản trừ nhóm B/C (đang chờ),
            SOS hỏng và dưới hỗ trợ được so với nhau theo 3 thành phần; mỗi thành phần là % số mã mà mã này hơn (0–100), điểm % là trung bình 3 thành phần:</p>
          <p style={{ margin: 0 }}>• <b>Cung cạn</b>: KL TB 10 phiên chia KL TB 60 phiên, càng thấp càng tốt (người bán cạn dần, đúng tinh thần Wyckoff).
            <br />• <b>Biến động thấp</b>: độ dao động giá ngày trong 20 phiên, càng thấp càng tốt.
            <br />• <b>Điểm sẵn sàng</b> của kế hoạch Wyckoff, càng cao càng tốt (chưa có kế hoạch tính 50).</p>
          <p style={{ margin: 0 }}>Cách chấm này được chọn sau khi đo riêng từng tiêu chí trên lịch sử 2019–2026: 3 thành phần trên và việc loại nhóm
            B/C · SOS hỏng · dưới hỗ trợ cho kết quả cùng chiều ở cả hai giai đoạn; RSI, MACD, khối ngoại, lời/lỗ của kế hoạch thì đổi chiều
            hoặc ngược chiều nên không tính. Danh sách có thể gồm mã chưa có điểm mua (vd đang tăng Pha E): khi đó chờ nhịp lùi theo kế hoạch.</p>
          <p className="muted" style={{ margin: 0, fontWeight: 600 }}>Tham khảo – công thức cũ (3 mục, mỗi mục 1/3), vẫn hiện trong phần chi tiết mỗi mã:</p>
          <p style={{ margin: 0 }}><b>1. Wyckoff.</b> Pha: Pha D ở LPS 40, D sớm 36, LPS chưa chắc 34, vừa SOS 30, sát trần 28,
            Pha B/C 18 (+12 nếu có Spring trong 15 phiên, +6 nếu có ST), dưới hỗ trợ 8–12, Pha E 10, SOS hỏng 6, mới tạo đáy 4.
            Điểm sẵn sàng: ≥ 80 được 20, 70–79 được 16, 60–69 được 12, dưới 60 chỉ 4 (backtest: R TB âm).
            Giá trong vùng vào 15, dưới vùng nhưng trên cắt lỗ 10, trên vùng ≤ 3% được 6. Lời/lỗ ≥ 3 được 15, ≥ 2 được 10, ≥ 1,5 được 5.
            Dư địa tới mục tiêu chính ≥ 25% được 10, ≥ 15% được 7, ≥ 8% được 4. Trừ 8 nếu có chuỗi đỉnh hạ, trừ 10 nếu đang có vùng phân phối.</p>
          <p style={{ margin: 0 }}><b>2. Kỹ thuật & Cơ bản</b> (5 phần × 20). RSI 14: 50–65 là 20, 65–75 là 14, 45–50 là 12, 35–45 là 8,
            trên 75 là 6, dưới 35 là 4. MACD: trên đường tín hiệu 8, histogram tăng 6, trên 0 được 6. MCDX: tay to bắt đầu vào 20,
            dẫn dắt 18, có mặt 12, giảm 7, chỉ đầu cơ 5, rút/không có 0. Ichimoku: trên mây 8 (trong mây 4), Tenkan &gt; Kijun 6,
            mây phía trước xanh 3, giá trên giá 26 phiên trước 3. BCTC: lãi 4 quý, tăng trưởng, ROE, biên lãi, nợ vay/VCSH
            (cùng ngưỡng thẻ Cơ bản; tốt = 1, trung bình = ½), không tính P/E vì không có số liệu theo từng thời điểm.</p>
          <p style={{ margin: 0 }}><b>3. Dòng tiền</b> (khối ngoại 50 + tự doanh 50): mua ròng 20 phiên so với giá trị giao dịch 20 phiên.
            Khối ngoại ±10% đạt tối đa/tối thiểu, tự doanh ±3%; không mua không bán = 25. Thiếu dữ liệu tính trung tính 25.
            Tự doanh tải lúc quét, chấp nhận trễ tối đa 2 phiên.</p>
          <p className="muted" style={{ margin: 0 }}>Đây là bảng xếp hạng tham khảo, không phải luật mua mới: tín hiệu, luật ẩn theo đèn và
            kế hoạch giao dịch không đổi. Không phải khuyến nghị đầu tư.</p>
        </div>
      </details>
    </>
  );
}
