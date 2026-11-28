"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import SectorCard from "@/components/SectorCard";
import IntradayCard from "@/components/IntradayCard";
import { api, Market, Row, Signal, GROUP_LABEL, STAGE_LABEL, fullDate, num, pct, price } from "@/lib/api";

type SortKey = "sym" | "sector" | "stage" | "chg" | "rs20" | "rs60" | "liq" | "dist" | "ready" | "rr" | "fx10" | "banker";
/** Giải thích từng cột (hiện khi rê chuột vào tên cột) */
const TIPS: Record<string, string> = {
  "Mã": "Mã cổ phiếu và sàn niêm yết.",
  "Ngành": "Ngành ICB của mã. Bấm tên ngành để lọc bảng theo ngành đó (giống ô chọn Ngành ICB).",
  "Pha": "Pha Wyckoff hiện tại. B/C: đang tích lũy trong vùng; sát trần: giá cách cận trên vùng ≤ 6%; D: đã bứt khỏi vùng (SOS); dưới hỗ trợ: thủng đáy vùng. Chữ nhỏ bên cạnh là sự kiện gần nhất (ST, Spring, LPS…); dấu * = đợt giảm trước đó yếu.",
  "Giá": "Giá đóng cửa phiên quét gần nhất (đồng).",
  "%": "Thay đổi giá so với phiên trước.",
  "Điểm": "Điểm sẵn sàng tăng 0–100 của vùng tích lũy (phát hiện sớm, trước khi bứt lên), cộng từ 5 phần, mỗi phần tối đa 20:\n• Cung cạn: KL 10 phiên gần nhất so với KL quanh đáy SC (≤ 50% = 20)\n• Đáy nâng dần (12) + có Spring KL thấp (8)\n• Vị trí trong vùng: ở 3/4 trên = 20, nửa trên = 10\n• RS: mạnh hơn VNINDEX 20 phiên (10) và 60 phiên (10)\n• Độ dài vùng tích lũy: ≥ 40 phiên = 20, ≥ 25 = 10\nTừ 70 điểm và cách trần ≤ 8% thì được đánh dấu 'sớm'. Điểm cao chưa phải tín hiệu mua: vẫn chờ điểm vào của kế hoạch.",
  "Vùng vào": "Vùng giá mua theo kế hoạch giao dịch. 🎯 = giá hiện tại đang nằm trong vùng. Mua trên vùng = mua đuổi.",
  "Cắt lỗ": "Giá cắt lỗ của kế hoạch: thủng mức này thì kịch bản sai, bán.",
  "Lời/lỗ": "Tỷ lệ lời/lỗ = (mục tiêu Nhân–Quả − giá vào) / (giá vào − cắt lỗ). Dưới 2 thì kế hoạch không mua.",
  "So trần": "Khoảng cách từ giá hiện tại tới trần vùng tích lũy (đỉnh AR, kháng cự). −10% nghĩa là còn 10% nữa mới chạm trần; số dương là đã vượt trần.",
  "RS20": "Sức mạnh tương đối 20 phiên: % tăng giảm của mã trừ % của VNINDEX trong 20 phiên. Dương = khỏe hơn thị trường.",
  "RS60": "Sức mạnh tương đối 60 phiên (khoảng 3 tháng), cách tính như RS20.",
  "GT (tỷ)": "Giá trị giao dịch trung bình 20 phiên, tỷ đồng/ngày. Dưới 10 tỷ: khó mua bán khối lượng lớn, trượt giá cao.",
  "NN 10p (tỷ)": "Khối ngoại mua ròng (+) / bán ròng (−) cộng dồn 10 phiên gần nhất, tỷ đồng.",
  "Banker": "MCDX Plus: phần cột đỏ ('tay to', RSI 50 phiên) theo % cột, ▲▼ là tăng/giảm so với 5 phiên trước, dòng dưới là trạng thái. 0% = xu hướng dài hạn chưa tăng. Chỉ để tham khảo, không phải dòng tiền thật. '–': lần quét cuối chưa có số liệu MCDX.",
  "Ghi chú": "Diễn biến gần đây: bật/lùi bao nhiêu % từ đáy/đỉnh nào, KL lùi lớn, chuỗi đỉnh hạ (cầu yếu) và mức giá phá chuỗi.",
};

const isEarly = (r: Row) => (r.stage === "BC" || r.stage === "near") && (r.ready ?? 0) >= 70 && (r.dist ?? -99) >= -8;
const STAGE_ORDER: Record<string, number> = { D: 0, near: 1, E: 2, BC: 3, below: 4, failed: 5, new: 6 };
const LIGHT_VN: Record<string, string> = { green: "Đèn xanh", yellow: "Đèn vàng", red: "Đèn đỏ" };

export default function Home() {
  const [market, setMarket] = useState<Market | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [date, setDate] = useState<string | null>(null);
  const [sigs, setSigs] = useState<Signal[]>([]);
  const [group, setGroup] = useState("all");
  const [sectorList, setSectorList] = useState<Record<string, string>>({});
  const [stage, setStage] = useState("all");
  const [minLiq, setMinLiq] = useState(10);
  const [q, setQ] = useState("");                 // tìm mã: lọc theo tiền tố, Enter mở trang mã
  // phóng to bảng toàn màn hình (Fullscreen API); Esc để thoát
  const tblBox = useRef<HTMLElement>(null);
  const [full, setFull] = useState(false);
  useEffect(() => {
    const on = () => setFull(document.fullscreenElement === tblBox.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  const toggleFull = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else tblBox.current?.requestFullscreen?.().catch(() => {});
  };
  const router = useRouter();
  const [sort, setSort] = useState<{ k: SortKey; desc: boolean }>({ k: "stage", desc: false });
  const [err, setErr] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [dates, setDates] = useState<string[]>([]);   // các phiên đã quét, mới nhất trước
  const [sel, setSel] = useState<string>("");          // phiên đang xem; "" = mới nhất (lưu ở URL ?date=)
  const old = !!sel && sel !== dates[0];

  const load = (d = sel) => {
    const qd = d ? "date=" + d : "";
    return Promise.all([
      api<Market>("/api/market?" + qd),
      api<{ date: string; rows: Row[]; sectors: Record<string, string> }>("/api/scan/latest?" + qd),
      api<Signal[]>("/api/signals?days=0" + (d ? "&until=" + d : "")),
      api<string[]>("/api/scan/dates"),
    ])
      .then(([m, s, g, ds]) => {
        setMarket(m); setRows(s.rows); setDate(s.date); setSigs(g); setSectorList(s.sectors ?? {}); setDates(ds); setErr(null);
      })
      .catch((e) => setErr(String(e)));
  };

  // đổi phiên: ghi vào URL (?date=) để tải lại / chia sẻ link vẫn đúng phiên
  const pick = (d: string) => {
    const v = d === dates[0] ? "" : d;
    setSel(v); load(v);
    router.replace(v ? "/?date=" + v : "/", { scroll: false });
  };

  useEffect(() => {
    const d = new URLSearchParams(window.location.search).get("date") ?? "";
    setSel(d); load(d);
  }, []);
  const at = old ? "?at=" + sel : "";

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
      if (!s.running) { clearInterval(t); setScanning(false); load(""); }
    }, 4000);
  };

  /** ngành ICB của mã (rỗng nếu chưa có trong danh sách niêm yết) */
  const secOf = (r: Row) => sectorList[r.groups.find((g) => g.startsWith("icb:")) ?? ""] ?? "";
  const view = useMemo(() => {
    const v = q ? rows.filter((r) => r.sym.startsWith(q)) : rows.filter((r) =>   // đang tìm mã: bỏ qua các bộ lọc khác
      (group === "all" || r.groups.includes(group)) &&
      (stage === "all" || (stage === "early" ? isEarly(r) || r.tag === "D sớm"
        : stage === "zone" ? !!r.in_zone : stage === "spring" ? r.test === "Spring"
        : stage === "test" ? r.test === "ST"
        : stage === "nearsc" ? r.sc != null && Math.abs(r.sc) <= 5 && !r.test : r.stage === stage)) && r.liq >= minLiq);
    const val = (r: Row): number | string =>
      sort.k === "sym" ? r.sym : sort.k === "sector" ? (secOf(r) || "￿") + r.sym : sort.k === "stage" ? STAGE_ORDER[r.stage] * 1000 - (r.rs20 ?? -99) : (r[sort.k] ?? -1e9);
    return v.sort((a, b) => {
      const x = val(a), y = val(b);
      const c = x < y ? -1 : x > y ? 1 : 0;
      return sort.desc ? -c : c;
    });
  }, [rows, group, stage, minLiq, sort, q, sectorList]);

  const th = (k: SortKey, label: string, n = false) => (
    <th className={n ? "n" : undefined} title={TIPS[label] + "\n(Bấm để sắp xếp)"}
      onClick={() => setSort((s) => ({ k, desc: s.k === k ? !s.desc : k !== "sym" && k !== "stage" && k !== "sector" }))}>
      <span className="tip">{label}</span>{sort.k === k ? (sort.desc ? " ▼" : " ▲") : ""}
    </th>
  );
  const plain = (label: string, n = false) => (
    <th className={n ? "n" : undefined} title={TIPS[label]}><span className="tip">{label}</span></th>
  );

  if (err) return <div className="card">Không kết nối được backend ({err}). Hãy chạy <code>scripts\start.bat</code>.</div>;

  return (
    <>
      <section className="card hero">
        <div style={{ display: "grid", gap: 4, minWidth: 0 }}>
          <div className="row" style={{ gap: 10 }}>
            <span className="eyebrow">VNINDEX{date ? ` · phiên ${fullDate(date)}` : ""}</span>
            {market?.light && <span className={`badge ${market.light}`}><span className={`light ${market.light}`} style={{ width: 8, height: 8, boxShadow: "none" }} />
              {LIGHT_VN[market.light] ?? market.light}</span>}
          </div>
          <div className="row" style={{ gap: 12, alignItems: "baseline" }}>
            <span className="idx">{price(market?.c, "pt")}</span>
            <span className={`chg ${(market?.chg ?? 0) >= 0 ? "up" : "down"}`}>{pct(market?.chg, 2)}</span>
          </div>
          <div className="muted" style={{ maxWidth: 780 }}>{market?.text}</div>
        </div>
        <div className="row">
          <label className="muted">Phiên{" "}
            <select id="session" className="btn" value={date ?? ""} onChange={(e) => pick(e.target.value)}
              disabled={dates.length < 2} title={dates.length < 2 ? "Mới có 1 phiên đã quét" : "Xem lại phiên đã quét"}>
              {!date && <option value="">–</option>}
              {dates.map((x, i) => <option key={x} value={x}>{fullDate(x)}{i === 0 ? " (mới nhất)" : ""}</option>)}
            </select></label>
          {!old && <>
            <button className="btn" onClick={rescan} disabled={scanning || !canScan}
              title={canScan ? undefined : "Chỉ quét được từ 15:00 thứ 2–6, sau khi phiên kết thúc"}>
              {scanning ? "Đang quét…" : "Quét lại"}</button>
            {!canScan && <span className="muted" style={{ fontSize: 12.5 }}>Quét từ 15:00 thứ 2–6</span>}
          </>}
        </div>
      </section>

      {old && date && <div className="notice">
        Đang xem phiên cũ {fullDate(date)}: bảng, đèn và tín hiệu là kết quả quét của phiên này.
        <button className="btn" onClick={() => pick(dates[0])}>Về phiên mới nhất</button>
      </div>}

      {!old && <IntradayCard />}

      <section className="card">
        <h2>Tín hiệu phiên {date ? fullDate(date) : ""} <span className="muted" style={{ fontWeight: 400, fontSize: 13.5 }}>· {sigs.length}</span></h2>
        {sigs.length === 0 ? <p className="muted">Không có tín hiệu.</p> : (
          <ul className="sig">
            {sigs.map((s) => (
              <li key={s.sym + s.kind}>
                <span className="pill">{s.kind}</span>{" "}
                {s.is_new ? "🆕 " : ""}<Link href={`/symbol/${s.sym}${at}`}><b>{s.sym}</b></Link> {s.text.replace(s.sym, "")}
              </li>
            ))}
          </ul>
        )}
      </section>

      <SectorCard date={date} active={group} onPick={setGroup} />

      <section ref={tblBox} className="card" style={{ display: "grid", gap: 12, alignContent: "start" }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="tabs">
            {["all", ...Object.keys(GROUP_LABEL)].map((g) => (
              <button key={g} className={group === g ? "on" : ""} onClick={() => setGroup(g)}>
                {g === "all" ? "Tất cả" : GROUP_LABEL[g]}
              </button>
            ))}
          </div>
          <div className="row">
            <form onSubmit={(e) => { e.preventDefault(); if (q) router.push(`/symbol/${q}${at}`); }}>
              <input id="search" type="search" placeholder="🔍 Mã (Enter để mở)" value={q} autoComplete="off"
                aria-label="Tìm mã cổ phiếu" maxLength={10} style={{ width: 170 }}
                onChange={(e) => setQ(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} />
            </form>
            <select id="sector" className="btn" value={group.startsWith("icb:") ? group : ""}
              onChange={(e) => setGroup(e.target.value || "all")}>
              <option value="">Ngành ICB…</option>
              {Object.entries(sectorList).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select id="stage" value={stage} onChange={(e) => setStage(e.target.value)} className="btn">
              <option value="all">Mọi pha</option>
              <option value="early">🔭 Tiềm năng sớm</option>
              <option value="zone">🎯 Đang trong vùng vào</option>
              <option value="spring">🌱 Spring: thủng đáy rồi đóng lại trên (15 phiên)</option>
              <option value="test">🌱 ST về đáy, chưa Spring (15 phiên)</option>
              <option value="nearsc">⏳ Sát đáy SC ±5%, chưa test (chờ Spring)</option>
              {Object.entries(STAGE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <label className="muted">GT ≥ <input id="minliq" type="number" value={minLiq} onChange={(e) => setMinLiq(+e.target.value)} style={{ width: 70 }} /> tỷ</label>
            <button className="btn" onClick={toggleFull} title={full ? "Thoát toàn màn hình (Esc)" : "Phóng to bảng toàn màn hình"}
              aria-label={full ? "Thoát toàn màn hình" : "Phóng to toàn màn hình"} style={{ padding: "0 9px" }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                {full
                  ? <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
                  : <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />}
              </svg>
            </button>
          </div>
        </div>
        <div className="tbl">
          <table className="right">
            <thead>
              <tr>
                {th("sym", "Mã")}{th("sector", "Ngành")}{th("stage", "Pha")}{plain("Giá", true)}{th("chg", "%", true)}{th("ready", "Điểm", true)}
                {plain("Vùng vào", true)}{plain("Cắt lỗ", true)}{th("rr", "Lời/lỗ", true)}
                {th("dist", "So trần", true)}{th("rs20", "RS20", true)}{th("rs60", "RS60", true)}{th("liq", "GT (tỷ)", true)}{th("fx10", "NN 10p (tỷ)", true)}{th("banker", "Banker", true)}{plain("Ghi chú")}
              </tr>
            </thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.sym}>
                  <td title={r.name ?? ""}><Link href={`/symbol/${r.sym}${at}`}><b>{r.sym}</b></Link>{" "}
                    <span className="muted" style={{ fontSize: 11.5 }}>{r.floor ?? ""}</span></td>
                  <td style={{ maxWidth: 170, overflow: "hidden", textOverflow: "ellipsis", fontSize: 13 }} title={secOf(r)}>
                    {secOf(r)
                      ? <button onClick={() => setGroup(r.groups.find((g) => g.startsWith("icb:"))!)} title={`${secOf(r)} · bấm để lọc ngành này`}
                          style={{ border: 0, background: "none", padding: 0, cursor: "pointer", color: "var(--muted)", font: "inherit", maxWidth: "100%",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{secOf(r)}</button>
                      : <span className="muted">–</span>}</td>
                  <td><span className={`pill ${r.stage}`}>{r.tag}</span>
                    {r.test && <span className="muted" style={{ fontSize: 11.5 }}
                      title={r.test === "Spring" ? "Thủng đáy thấp nhất trước đó rồi đóng cửa lại trên đáy vùng (Pha C) trong 15 phiên" : "Quay về chạm/gần đáy vùng nhưng không thủng đáy cũ (ST) trong 15 phiên"}>
                      {" "}🌱{r.test}</span>}
                    {stage === "nearsc" && r.sc != null && <div className="muted" style={{ fontSize: 11.5 }}
                      title="KL < 1 lần TB20 khi thủng/chạm đáy là dấu hiệu Spring thật; KL ≥ 1,5 lần mà đóng dưới đáy là gãy thật">
                      SC {pct(r.sc)} · KL x{num(r.vx, 1)}</div>}
                    {r.weak_drop ? <span className="muted" title="Đợt giảm trước đó dưới 20%"> *</span> : null}</td>
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
                  <td className={`n ${r.fx10 == null ? "muted" : r.fx10 >= 0 ? "up" : "down"}`}>
                    {r.fx10 == null ? "–" : (r.fx10 > 0 ? "+" : "") + num(r.fx10, 1)}</td>
                  <td className="n" title="MCDX Plus: % cột của banker (đỏ); mũi tên = thay đổi 5 phiên"
                    style={{ color: r.banker == null ? "var(--muted)" : r.banker >= 50 ? "#dc2626" : undefined, fontWeight: (r.banker ?? 0) >= 50 ? 700 : 400 }}>
                    {r.banker == null ? "–" : num(r.banker, 0) + "%"}
                    {r.banker_chg5 ? <span className={r.banker_chg5 > 0 ? "up" : "down"} style={{ fontSize: 11 }}> {r.banker_chg5 > 0 ? "▲" : "▼"}</span> : null}
                    {r.banker_label && <div style={{ fontFamily: "var(--font)", fontSize: 11, fontWeight: 500,
                      color: r.banker_tone === "good" ? "var(--up)" : r.banker_tone === "bad" ? "var(--down)" : r.banker_tone === "warn" ? "var(--warn)" : "var(--muted)" }}>
                      {r.banker_label}</div>}</td>
                  <td className="muted" style={{ whiteSpace: "normal", minWidth: 220, fontSize: 13 }}>{r.extra}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
          {view.length}/{rows.length} mã · Điểm = mức sẵn sàng tăng 0–100 · 🎯 giá đang trong vùng vào ·
          Lời/lỗ tính tới mục tiêu Nhân–Quả · RS = chênh lệch % so với VNINDEX · So trần = khoảng cách tới trần (AR) · NN 10p = khối ngoại mua ròng 10 phiên · Banker = MCDX Plus, % cột của “tay to” (RSI 50 phiên tách tầng; ▲▼ so với 5 phiên trước) · * đợt giảm trước đó yếu
        </p>
      </section>
    </>
  );
}
