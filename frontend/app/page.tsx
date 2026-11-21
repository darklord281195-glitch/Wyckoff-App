"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, Market, Row, Signal, GROUP_LABEL, STAGE_LABEL, fullDate, num, pct, price } from "@/lib/api";

type SortKey = "sym" | "stage" | "chg" | "rs20" | "rs60" | "liq" | "dist" | "ready" | "rr";
const isEarly = (r: Row) => (r.stage === "BC" || r.stage === "near") && (r.ready ?? 0) >= 70 && (r.dist ?? -99) >= -8;
const STAGE_ORDER: Record<string, number> = { D: 0, near: 1, E: 2, BC: 3, below: 4, failed: 5, new: 6 };

export default function Home() {
  const [market, setMarket] = useState<Market | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [date, setDate] = useState<string | null>(null);
  const [sigs, setSigs] = useState<Signal[]>([]);
  const [group, setGroup] = useState("all");
  const [sectorList, setSectorList] = useState<Record<string, string>>({});
  const [stage, setStage] = useState("all");
  const [minLiq, setMinLiq] = useState(10);
  const [sort, setSort] = useState<{ k: SortKey; desc: boolean }>({ k: "stage", desc: false });
  const [err, setErr] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  const load = () =>
    Promise.all([
      api<Market>("/api/market"),
      api<{ date: string; rows: Row[]; sectors: Record<string, string> }>("/api/scan/latest"),
      api<Signal[]>("/api/signals?days=0"),
    ])
      .then(([m, s, g]) => {
        setMarket(m); setRows(s.rows); setDate(s.date); setSigs(g); setSectorList(s.sectors ?? {}); setErr(null);
      })
      .catch((e) => setErr(String(e)));

  useEffect(() => { load(); }, []);

  // giống scan_allowed() ở backend: chỉ từ 15:00 thứ 2–6 giờ VN; kiểm tra lại mỗi 30 giây
  const vnOpen = () => { const n = new Date(Date.now() + 7 * 3600e3); return n.getUTCDay() >= 1 && n.getUTCDay() <= 5 && n.getUTCHours() >= 15; };
  const [canScan, setCanScan] = useState(vnOpen);
  useEffect(() => { const t = setInterval(() => setCanScan(vnOpen()), 30000); return () => clearInterval(t); }, []);

  const rescan = async () => {
    setScanning(true);
    try { await api("/api/scan/run?dry_run=true", { method: "POST" }); }
    catch (e) { setScanning(false); window.alert(String(e)); return; }   // vd 403 ngoài giờ cho phép
    const t = setInterval(async () => {
      const s = await api<{ running: boolean }>("/api/scan/status");
      if (!s.running) { clearInterval(t); setScanning(false); load(); }
    }, 4000);
  };

  const view = useMemo(() => {
    const v = rows.filter((r) =>
      (group === "all" || r.groups.includes(group)) &&
      (stage === "all" || (stage === "early" ? isEarly(r) || r.tag === "D sớm"
        : stage === "zone" ? !!r.in_zone : r.stage === stage)) && r.liq >= minLiq);
    const val = (r: Row): number | string =>
      sort.k === "sym" ? r.sym : sort.k === "stage" ? STAGE_ORDER[r.stage] * 1000 - (r.rs20 ?? -99) : (r[sort.k] ?? -1e9);
    return v.sort((a, b) => {
      const x = val(a), y = val(b);
      const c = x < y ? -1 : x > y ? 1 : 0;
      return sort.desc ? -c : c;
    });
  }, [rows, group, stage, minLiq, sort]);

  const th = (k: SortKey, label: string) => (
    <th onClick={() => setSort((s) => ({ k, desc: s.k === k ? !s.desc : k !== "sym" && k !== "stage" }))}>
      {label}{sort.k === k ? (sort.desc ? " ▼" : " ▲") : ""}
    </th>
  );

  if (err) return <div className="card">Không kết nối được backend ({err}). Hãy chạy <code>scripts\start.bat</code>.</div>;

  return (
    <>
      <section className="card row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <span className={`light ${market?.light}`} />
          <div>
            <div style={{ fontWeight: 600 }}>
              VNINDEX <span className="mono">{price(market?.c, "pt")}</span>{" "}
              <span className={(market?.chg ?? 0) >= 0 ? "up" : "down"}>{pct(market?.chg, 2)}</span>
            </div>
            <div className="muted">{market?.text}</div>
          </div>
        </div>
        <div className="row">
          <span className="muted">Phiên {date ? fullDate(date) : "–"}</span>
          <button className="btn" onClick={rescan} disabled={scanning || !canScan}
            title={canScan ? undefined : "Chỉ quét được từ 15:00 thứ 2–6, sau khi phiên kết thúc"}>
            {scanning ? "Đang quét…" : "Quét lại"}</button>
          {!canScan && <span className="muted" style={{ fontSize: 12.5 }}>Quét từ 15:00 thứ 2–6</span>}
        </div>
      </section>

      <section className="card">
        <h2>Tín hiệu phiên {date ? fullDate(date) : ""}</h2>
        {sigs.length === 0 ? <p className="muted">Không có tín hiệu.</p> : (
          <ul className="sig">
            {sigs.map((s) => (
              <li key={s.sym + s.kind}>
                <span className="pill">{s.kind}</span>{" "}
                {s.is_new ? "🆕 " : ""}<Link href={`/symbol/${s.sym}`}><b>{s.sym}</b></Link> {s.text.replace(s.sym, "")}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card" style={{ display: "grid", gap: 12 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="tabs">
            {["all", ...Object.keys(GROUP_LABEL)].map((g) => (
              <button key={g} className={group === g ? "on" : ""} onClick={() => setGroup(g)}>
                {g === "all" ? "Tất cả" : GROUP_LABEL[g]}
              </button>
            ))}
          </div>
          <div className="row">
            <select id="sector" className="btn" value={group.startsWith("icb:") ? group : ""}
              onChange={(e) => setGroup(e.target.value || "all")}>
              <option value="">Ngành ICB…</option>
              {Object.entries(sectorList).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select id="stage" value={stage} onChange={(e) => setStage(e.target.value)} className="btn">
              <option value="all">Mọi pha</option>
              <option value="early">🔭 Tiềm năng sớm</option>
              <option value="zone">🎯 Đang trong vùng vào</option>
              {Object.entries(STAGE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <label className="muted">GT ≥ <input id="minliq" type="number" value={minLiq} onChange={(e) => setMinLiq(+e.target.value)} style={{ width: 70 }} /> tỷ</label>
          </div>
        </div>
        <div className="tbl">
          <table>
            <thead>
              <tr>
                {th("sym", "Mã")}{th("stage", "Pha")}<th>Giá</th>{th("chg", "%")}{th("ready", "Điểm")}
                <th>Vùng vào</th><th>Cắt lỗ</th>{th("rr", "Lời/lỗ")}
                {th("dist", "So trần")}{th("rs20", "RS20")}{th("rs60", "RS60")}{th("liq", "GT (tỷ)")}<th>Ghi chú</th>
              </tr>
            </thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.sym}>
                  <td title={r.name ?? ""}><Link href={`/symbol/${r.sym}`}><b>{r.sym}</b></Link>{" "}
                    <span className="muted" style={{ fontSize: 11.5 }}>{r.floor ?? ""}</span></td>
                  <td><span className={`pill ${r.stage}`}>{r.tag}</span>{r.weak_drop ? <span className="muted" title="Đợt giảm trước đó dưới 20%"> *</span> : null}</td>
                  <td className="n">{price(r.c)}</td>
                  <td className={`n ${r.chg >= 0 ? "up" : "down"}`}>{pct(r.chg, 2)}</td>
                  <td className="n" style={{ fontWeight: (r.ready ?? 0) >= 70 ? 700 : 400 }}>{num(r.ready)}</td>
                  <td className="n" title={r.plan_kind ?? ""}>
                    {r.entry_lo ? `${price(r.entry_lo)}–${price(r.entry_hi)}` : "–"}{r.in_zone ? " 🎯" : ""}
                  </td>
                  <td className="n down">{price(r.stop)}</td>
                  <td className={`n ${(r.rr ?? 0) >= 2 ? "up" : ""}`}>{r.rr != null ? num(r.rr, 1) : "–"}</td>
                  <td className="n">{pct(r.dist)}</td>
                  <td className={`n ${(r.rs20 ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.rs20)}</td>
                  <td className={`n ${(r.rs60 ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.rs60)}</td>
                  <td className="n">{num(r.liq)}</td>
                  <td className="muted" style={{ whiteSpace: "normal" }}>{r.extra}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
          {view.length}/{rows.length} mã · Điểm = mức sẵn sàng tăng 0–100 · 🎯 giá đang trong vùng vào ·
          Lời/lỗ tính tới mục tiêu Nhân–Quả · RS = chênh lệch % so với VNINDEX · So trần = khoảng cách tới trần (AR) · * đợt giảm trước đó yếu
        </p>
      </section>
    </>
  );
}
