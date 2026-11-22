"use client";
import Link from "next/link";
import dynamic from "next/dynamic";
import { use, useEffect, useState } from "react";
import { api, SymbolData, GROUP_LABEL, day, fullDate, num, pct, price } from "@/lib/api";

const WyckoffChart = dynamic(() => import("@/components/WyckoffChart"), { ssr: false });
import PlanCard from "@/components/PlanCard";
import ForeignCard from "@/components/ForeignCard";
import FundamentalsCard from "@/components/FundamentalsCard";
import WyckoffSchematic, { WYCKOFF_NOTES, DIST_NOTES } from "@/components/WyckoffSchematic";

const STAGE_HINT: Record<string, string> = {
  "D-LPS": "Đang lùi với KL thấp sau SOS: vùng mua LPS. Đặt cắt lỗ dưới mốc Hỏng.",
  "D-LPS?": "Đang lùi nhưng KL chưa cạn: chờ KL giảm hẳn rồi mới tính.",
  "D-SOS": "Vừa bật lên sau SOS: không đuổi giá, chờ Backup/LPS về gần trần cũ.",
  "D sớm": "Bật từ Spring/ST lên sát trần: chờ vượt trần với KL lớn (SOS).",
  "sát trần": "Chưa có SOS: theo dõi phiên vượt trần với KL ≥ 1,5 lần TB20.",
  "E?": "Đã chạy xa trần (Pha E?): không mua đuổi, chờ nền tái tích lũy.",
  "SOS hỏng": "Vượt trần rồi rơi sâu lại vào vùng: cấu trúc yếu.",
  "B/C": "Đang trong vùng (Pha B/C): chưa có điểm mua theo Wyckoff.",
  "dưới hỗ trợ": "Giá đóng cửa dưới đáy vùng: chưa mua. Chờ phiên đóng cửa trở lại trên hỗ trợ với KL thấp (Spring).",
};

export default function SymbolPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const [d, setD] = useState<SymbolData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [at, setAt] = useState<string | null>(null);     // ngày đang xem (?at=); null = phiên mới nhất
  const [start, setStart] = useState<string | null>(null); // đầu khoảng chọn trên biểu đồ (?from=), cuối khoảng = at
  const [ready, setReady] = useState(false);              // đã đọc ?at=&from= từ URL

  const qs = (a: string | null, s: string | null) =>
    a ? "?" + (s ? "from=" + s + "&" : "") + "at=" + a : "";
  const load = () => api<SymbolData>("/api/symbols/" + code + qs(at, start))
    .then((x) => { setD(x); setErr(null); }).catch((e) => setErr(String(e)));
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setAt(p.get("at")); setStart(p.get("at") ? p.get("from") : null); setReady(true);
  }, [code]);
  useEffect(() => { if (ready) load(); }, [code, at, start, ready]);

  // đổi ngày / khoảng: ghi vào URL để tải lại / chia sẻ vẫn đúng
  const pick = (a: string | null, s: string | null = null) => {
    setAt(a || null); setStart(a ? s : null);
    window.history.replaceState(null, "", qs(a || null, s) || window.location.pathname);
  };
  const pickDay = (v: string | null) => pick(v);

  const toggleWl = async () => {
    if (!d) return;
    if (d.in_watchlist) await api(`/api/watchlist/${d.sym}`, { method: "DELETE" });
    else await api(`/api/watchlist`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sym: d.sym }) });
    load();
  };

  if (err) return <div className="card">Lỗi: {err}{at && <> <button className="btn" onClick={() => pickDay(null)}>Về phiên mới nhất</button></>}</div>;
  if (!d) return <div className="card">Đang tải {code}…</div>;
  const a = d.analysis, u = d.unit;
  const lv = (a?.levels ?? {}) as { support?: number; resistance?: number; invalid?: number };

  return (
    <>
      <section className="card row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <h1>{d.sym}</h1>
          {a && <span className={`pill ${a.stage}`}>{a.tag}</span>}
          <span className="muted">
            {[d.name, d.floor, d.sector, ...d.groups.filter((g) => GROUP_LABEL[g]).map((g) => GROUP_LABEL[g])]
              .filter(Boolean).join(" · ")}
          </span>
        </div>
        <div className="row">
          {a && <span className="mono" style={{ fontSize: 18 }}>{price(a.c, u)}{" "}
            <span className={a.chg >= 0 ? "up" : "down"}>{pct(a.chg, 2)}</span></span>}
          <label className="muted">Ngày <input id="at" type="date" value={at ?? a?.d ?? ""} max={new Date().toISOString().slice(0, 10)}
            onChange={(e) => pickDay(e.target.value)} /></label>
          {u === "k" && <button className="btn" onClick={toggleWl}>{d.in_watchlist ? "★ Bỏ theo dõi" : "☆ Theo dõi"}</button>}
        </div>
      </section>

      {at && a && <div className="notice">
        {start
          ? <>Phân tích Wyckoff trong khoảng {fullDate(start)} – {fullDate(a.d)}: chỉ dò vùng trong khoảng này và chỉ dùng dữ liệu tới {fullDate(a.d)}.</>
          : <>Đang xem {d.sym} tại phiên {fullDate(a.d)}: phân tích và kế hoạch chỉ dùng dữ liệu tới phiên này.</>}
        {" "}Nến sau đó trên biểu đồ là diễn biến thực tế.
        <button className="btn" onClick={() => pickDay(null)}>Về phiên mới nhất</button>
      </div>}

      <section className="card"><WyckoffChart data={d.ohlcv} analysis={a} unit={u} stats={d.plan_stats}
        sel={at ? { from: start ?? at, to: at } : null} onRange={(f, t) => pick(t, f)} /></section>

      {u === "k" && <FundamentalsCard f={d.fundamentals ?? null} at={at} />}

      {u === "k" && <ForeignCard rows={d.foreign ?? []} error={d.foreign_error} />}

      {a?.plan && u === "k" && <PlanCard sym={d.sym} plan={a.plan} c={a.c} unit={u} readOnly={!!at} />}

      {a && (
        <div className="grid2">
          <section className="card">
            <h2>Các mốc Wyckoff</h2>
            <div className="tbl">
              <table style={{ minWidth: 420 }}>
                <thead><tr><th>Sự kiện</th><th>Ngày</th><th>Giá</th><th>KL (tr)</th><th>KL/TB20</th></tr></thead>
                <tbody>
                  {a.events.map((e) => (
                    <tr key={e.d + e.k}>
                      <td title={WYCKOFF_NOTES[e.k] ? `${WYCKOFF_NOTES[e.k].name}: ${WYCKOFF_NOTES[e.k].what}` : undefined}
                        style={{ cursor: WYCKOFF_NOTES[e.k] ? "help" : undefined }}><b>{e.k}</b></td>
                      <td className="n">{fullDate(e.d)}</td>
                      <td className="n">{price(e.price, u)}</td><td className="n">{num(e.v, 2)}</td>
                      <td className="n">{e.vx ? "x" + num(e.vx, 1) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p style={{ marginBottom: 0 }}>{STAGE_HINT[a.tag] ?? ""} {a.extra ? <span className="muted">({a.extra})</span> : null}</p>
            {a.distrib && (
              <p style={{ marginBottom: 0 }}>
                <b className="down">Phân phối: {a.distrib.tag}</b>{" "}
                <span className="muted">vùng {price(a.distrib.bot, u)} – {price(a.distrib.top, u)} từ {fullDate(a.distrib.start)} · </span>
                {a.distrib.events.map((e, i) => (
                  <span key={e.d + e.k} title={DIST_NOTES[e.k] ? `${DIST_NOTES[e.k].name}: ${DIST_NOTES[e.k].what}` : undefined}
                    style={{ cursor: DIST_NOTES[e.k] ? "help" : undefined }}>
                    {i ? " · " : ""}{e.k} {day(e.d)}</span>
                ))}
                <br /><span className="muted" style={{ fontSize: 12.5 }}>
                  Kiểm chứng 2019–2026: chỉ UTAD có tác dụng (yếu) — mã đang giữ/theo dõi gặp UTAD sẽ được báo; SOW/LPSY chỉ để tham khảo.
                </span>
              </p>
            )}
          </section>

          <section className="card">
            <h2>Mốc giá & chỉ số</h2>
            <dl className="kv">
              <dt>Hỗ trợ</dt><dd>{price(lv.support, u)}</dd>
              <dt>Kháng cự</dt><dd>{price(lv.resistance, u)}</dd>
              <dt>Mốc hỏng</dt><dd className="down">{price(lv.invalid, u)}</dd>
              <dt>Vùng</dt><dd>{a.range ? `${price(a.range.sup, u)} – ${price(a.range.res, u)}` : "–"}</dd>
              <dt>MA20 / 50 / 200</dt><dd>{price(a.ma20, u)} / {price(a.ma50, u)} / {price(a.ma200, u)}</dd>
              <dt>Vị trí 52 tuần</dt><dd>{num(a.pos52)}%</dd>
              {u === "k" && <><dt>RS 5 / 20 / 60</dt><dd>{pct(a.rs5)} / {pct(a.rs20)} / {pct(a.rs60)}</dd></>}
              {u === "k" && <><dt>GT TB20</dt><dd>{num(a.liq)} tỷ/ngày</dd></>}
              <dt>KL phiên cuối</dt><dd>{num(a.v, 2)} tr {a.vx ? `(x${num(a.vx, 1)})` : ""}</dd>
            </dl>
            <h2 style={{ marginTop: 16 }}>Lịch sử tín hiệu</h2>
            {d.signals.length === 0 ? <p className="muted">Chưa có.</p> : (
              <ul className="sig">
                {d.signals.map((s) => <li key={s.date + s.kind}><span className="mono">{day(s.date)}</span> <span className="pill">{s.kind}</span> {s.text.replace(d.sym, "")}</li>)}
              </ul>
            )}
          </section>
        </div>
      )}
      <section className="card">
        <h2>Sơ đồ mẫu Wyckoff</h2>
        {a?.schema && (
          <p style={{ marginTop: 0 }}>
            <b>{d.sym}</b> đang giống: <b style={{ color: "var(--accent)" }}>{a.schema.title}</b>
            {a.schema.phase && <> · <b>Pha {a.schema.phase}</b></>}
            <br /><span className="muted">{a.schema.note}</span>
          </p>
        )}
        <WyckoffSchematic key={d.sym} variant={a?.schema?.variant} phase={a?.schema?.phase} />
      </section>
      <Link href="/" className="muted">← Về tổng quan</Link>
    </>
  );
}
