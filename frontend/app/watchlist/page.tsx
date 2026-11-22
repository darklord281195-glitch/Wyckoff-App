"use client";
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { api, Position, Row, Sale, day, fullDate, num, pct, price } from "@/lib/api";
import RiskCard from "@/components/RiskCard";

type Item = { sym: string; note: string | null; added: string };
const JSON_HDR = { "Content-Type": "application/json" };

export default function Watchlist() {
  const [items, setItems] = useState<Item[]>([]);
  const [pos, setPos] = useState<Position[]>([]);
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [sym, setSym] = useState(""); const [note, setNote] = useState("");
  const [sales, setSales] = useState<Sale[]>([]);
  const [sell, setSell] = useState<{ id: number; qty: string; px: string; d: string } | null>(null);  // form bán đang mở
  const [sellErr, setSellErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);        // tăng mỗi lần tải lại để RiskCard tính lại

  const load = async () => {
    setItems(await api<Item[]>("/api/watchlist"));
    setPos(await api<Position[]>("/api/positions"));
    setSales(await api<Sale[]>("/api/sales"));
    const s = await api<{ rows: Row[] }>("/api/scan/latest");
    setRows(Object.fromEntries(s.rows.map((r) => [r.sym, r])));
    setTick((t) => t + 1);
  };
  useEffect(() => { load(); }, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sym.trim()) return;
    await api("/api/watchlist", { method: "POST", headers: JSON_HDR,
      body: JSON.stringify({ sym: sym.trim().toUpperCase(), note: note || null }) });
    setSym(""); setNote(""); load();
  };
  const del = async (s: string) => { await api(`/api/watchlist/${s}`, { method: "DELETE" }); load(); };
  const held = (p: Position) => (p.qty != null ? p.qty - p.sold : null);
  const openSell = (p: Position) => {
    setSellErr(null);
    setSell({ id: p.id, qty: String(held(p) ?? ""), px: String(Math.round((p.c ?? p.entry_px) * 1000)), d: "" });
  };
  const doSell = async () => {
    if (!sell) return;
    try {
      await api(`/api/positions/${sell.id}/sell`, { method: "POST", headers: JSON_HDR, body: JSON.stringify({
        qty: +sell.qty > 0 ? Math.floor(+sell.qty) : null, px: +sell.px > 0 ? +sell.px / 1000 : null, d: sell.d || null }) });
      setSell(null); load();
    } catch (e) { setSellErr(String(e)); }
  };
  const delSale = async (s: Sale) => {
    // lệnh đóng trước khi có bảng sales (id null) không có lần bán riêng -> xóa cả lệnh
    if (!window.confirm(s.id ? `Xóa lần bán ${s.sym} ${num(s.qty)} cp ngày ${fullDate(s.d)}? Lệnh sẽ được mở lại phần cp này.`
      : `Xóa lệnh ${s.sym} khỏi lịch sử?`)) return;
    await api(s.id ? `/api/sales/${s.id}` : `/api/positions/${s.pos_id}`, { method: "DELETE" });
    load();
  };
  const realized =sales.reduce((s, x) => s + (x.pnl_vnd ?? 0), 0);
  const setStop = async (p: Position, v: number) => {
    if (!(v > 0) || v === Math.round((p.cur_stop ?? 0) * 1000)) return;
    if (p.c && v / 1000 >= p.c && !window.confirm(`Cắt lỗ ${num(v)} ≥ giá hiện tại: app sẽ báo bán ngay. Tiếp tục?`)) { load(); return; }
    await api(`/api/positions/${p.id}`, { method: "PATCH", headers: JSON_HDR, body: JSON.stringify({ stop: v / 1000 }) });
    load();
  };

  return (
    <>
      <RiskCard reload={tick} />

      <section className="card">
        <h2>Danh mục đang giữ</h2>
        {pos.length === 0 ? (
          <p className="muted">Chưa có lệnh. Mở trang một mã, ở mục Kế hoạch giao dịch bấm &quot;Ghi nhận đã mua&quot;.</p>
        ) : (
          <div className="tbl">
            <table>
              <thead><tr><th>Mã</th><th>Ngày mua</th><th>Giá vốn</th><th>KL</th><th>Giá</th><th>Lãi/lỗ</th>
                <th>Cắt lỗ hiện tại</th><th>Mục tiêu kế tiếp</th><th>Còn giữ</th><th>Phiên</th><th>Việc gần nhất</th><th></th></tr></thead>
              <tbody>
                {pos.map((p) => {
                  const e = p.events?.[p.events.length - 1];
                  return (
                    <Fragment key={p.id}>
                    <tr>
                      <td><Link href={`/symbol/${p.sym}`}><b>{p.sym}</b></Link></td>
                      <td className="n">{fullDate(p.entry_d)}</td>
                      <td className="n">{price(p.entry_px)}</td>
                      <td className="n">{p.sold && p.qty ? `${num(held(p))}/${num(p.qty)}` : num(p.qty)}</td>
                      <td className="n">{price(p.c)}</td>
                      <td className={`n ${(p.pnl ?? 0) >= 0 ? "up" : "down"}`}>{pct(p.pnl)}</td>
                      <td className="n down">
                        {/* key theo mốc để ô tự cập nhật sau khi lưu; Enter hoặc rời ô là lưu */}
                        <input key={p.cur_stop} type="number" step={10} min={1} aria-label={`Cắt lỗ ${p.sym}`}
                          defaultValue={p.cur_stop ? Math.round(p.cur_stop * 1000) : ""} style={{ width: 90 }}
                          onBlur={(ev) => setStop(p, +ev.target.value)}
                          onKeyDown={(ev) => { if (ev.key === "Enter") ev.currentTarget.blur(); }} />
                        {p.cur_stop && p.c ? <span className="muted"> ({pct((p.cur_stop / p.c - 1) * 100)})</span> : null}
                      </td>
                      <td className="n up">{price(p.next)}</td>
                      <td className="n">{p.left != null ? `${num(p.left * 100)}%` : "–"}</td>
                      <td className="n">{num(p.days)}</td>
                      <td style={{ whiteSpace: "normal" }}>
                        {e ? <span className={p.pending ? "down" : ""} style={{ fontWeight: p.pending ? 600 : 400 }}>
                          {day(e.d)} · {e.kind}: {e.text}</span> : <span className="muted">Giữ, chưa có việc</span>}
                        {p.sold_out && <b><br />Theo luật đã bán hết ngày {day(p.sold_out)}: bán xong thì bấm Bán để ghi lại</b>}
                      </td>
                      <td><button className="btn" onClick={() => (sell?.id === p.id ? setSell(null) : openSell(p))}>Bán</button></td>
                    </tr>
                    {sell?.id === p.id && (
                      <tr><td colSpan={12}>
                        <div className="row">
                          <b>Bán {p.sym}</b>
                          <label className="muted">Số lượng <input type="number" min={1} step={100} value={sell.qty}
                            placeholder="tất cả" onChange={(e) => setSell({ ...sell, qty: e.target.value })} style={{ width: 90 }} /> cp
                            {held(p) != null && <> (còn {num(held(p))})</>}</label>
                          <label className="muted">Giá <input type="number" min={1} step={10} value={sell.px}
                            onChange={(e) => setSell({ ...sell, px: e.target.value })} style={{ width: 100 }} /> đ</label>
                          <label className="muted">Ngày <input type="date" value={sell.d}
                            onChange={(e) => setSell({ ...sell, d: e.target.value })} /></label>
                          <button className="btn primary" onClick={doSell}>Xác nhận bán</button>
                          <button className="btn" onClick={() => setSell(null)}>Hủy</button>
                          {sellErr && <span className="down">{sellErr}</span>}
                        </div>
                      </td></tr>
                    )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
          Luật bán: chạm T1 bán 1/3 và dời cắt lỗ về giá vốn · T2 bán thêm 1/3 · phần còn lại dời cắt lỗ theo đáy thấp nhất
          10 phiên · đóng cửa dưới cắt lỗ thì bán phiên sau (hàng về chiều T+2) · 20 phiên chưa chạm T1 thì bán.
          Cắt lỗ và mục tiêu chốt theo kế hoạch tại ngày mua.
        </p>
      </section>

      <section className="card">
        <h2>Lịch sử bán</h2>
        {sales.length === 0 ? <p className="muted">Chưa có lần bán nào.</p> : (
          <div className="tbl">
            <table>
              <thead><tr><th>Ngày bán</th><th>Mã</th><th>Ngày mua</th><th>Giá vốn</th><th>Giá bán</th><th>KL</th>
                <th>Lãi/lỗ</th><th>Lãi/lỗ (đ)</th><th></th></tr></thead>
              <tbody>
                {sales.map((s) => (
                  <tr key={`${s.pos_id}-${s.id ?? "x"}`}>
                    <td className="n">{fullDate(s.d)}</td>
                    <td><Link href={`/symbol/${s.sym}`}><b>{s.sym}</b></Link></td>
                    <td className="n">{fullDate(s.entry_d)}</td>
                    <td className="n">{price(s.entry_px)}</td>
                    <td className="n">{price(s.px)}</td>
                    <td className="n">{num(s.qty)}</td>
                    <td className={`n ${s.pnl >= 0 ? "up" : "down"}`}>{pct(s.pnl)}</td>
                    <td className={`n ${(s.pnl_vnd ?? 0) >= 0 ? "up" : "down"}`}>{s.pnl_vnd != null ? num(s.pnl_vnd) : "–"}</td>
                    <td><button className="btn" onClick={() => delSale(s)}>Xóa</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {sales.length > 0 && <p style={{ margin: "8px 0 0" }}>Tổng lãi/lỗ đã chốt:{" "}
          <b className={realized >= 0 ? "up" : "down"}>{num(realized)} đ</b>
          <span className="muted"> · sau phí mua 0,15%, bán 0,15% + thuế 0,1%</span></p>}
      </section>

      <section className="card">
        <h2>Thêm mã theo dõi</h2>
        <form onSubmit={add} className="row">
          <input id="wl-sym" placeholder="Mã (vd TCH)" value={sym} onChange={(e) => setSym(e.target.value)} style={{ width: 120 }} />
          <input id="wl-note" placeholder="Ghi chú (vd chờ Backup 13.650)" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          <button className="btn primary" type="submit">Thêm</button>
        </form>
        <p className="muted" style={{ marginBottom: 0 }}>Mã trong watchlist luôn được quét mỗi ngày và có cảnh báo khi gãy cấu trúc.</p>
      </section>
      <section className="card tbl">
        <table>
          <thead><tr><th>Mã</th><th>Pha (lần quét gần nhất)</th><th>Giá</th><th>%</th><th>RS20</th><th>Ghi chú</th><th>Ngày thêm</th><th></th></tr></thead>
          <tbody>
            {items.map((it) => {
              const r = rows[it.sym];
              return (
                <tr key={it.sym}>
                  <td><Link href={`/symbol/${it.sym}`}><b>{it.sym}</b></Link></td>
                  <td>{r ? <span className={`pill ${r.stage}`}>{r.tag}</span> : <span className="muted">chưa quét</span>}</td>
                  <td className="n">{r ? price(r.c) : "–"}</td>
                  <td className={`n ${(r?.chg ?? 0) >= 0 ? "up" : "down"}`}>{r ? pct(r.chg, 2) : "–"}</td>
                  <td className="n">{r ? pct(r.rs20) : "–"}</td>
                  <td style={{ whiteSpace: "normal" }}>{it.note}</td>
                  <td className="n">{fullDate(it.added)}</td>
                  <td><button className="btn" onClick={() => del(it.sym)}>Xóa</button></td>
                </tr>
              );
            })}
            {items.length === 0 && <tr><td colSpan={8} className="muted">Chưa có mã nào.</td></tr>}
          </tbody>
        </table>
      </section>
    </>
  );
}
