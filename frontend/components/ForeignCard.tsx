"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { createChart, ColorType, IChartApi, LineStyle, Time } from "lightweight-charts";
import { day, fullDate, num, type Foreign } from "@/lib/api";

const RANGES = [10, 30, 50, 90, 250];
const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const ty = (x: number, d = 1) => (x > 0 ? "+" : "") + num(x, d);          // tỷ đồng có dấu

type Flow = { d: string; buy: number; sell: number; net: number; room?: number | null; total_room?: number | null };

/** Dòng tiền khối ngoại / tự doanh CTCK: cột giá trị mua ròng từng phiên (xanh mua ròng, đỏ bán ròng), đường lũy kế
 *  (trục trái) để thấy gom hay xả dần, và tổng hợp theo khoảng. "Theo vùng" = từ đáy vùng Wyckoff (SC) tới nay. */
export default function ForeignCard({ rows: fxRows, error, prop, propError, rangeStart }: {
  rows: Foreign[]; error?: string | null; prop?: Flow[]; propError?: string | null; rangeStart?: string | null }) {
  const [src, setSrc] = useState<"fx" | "prop">("fx");
  const rows: Flow[] = useMemo(() => (src === "fx" ? fxRows : prop ?? []), [src, fxRows, prop]);
  const [n, setN] = useState<number | "range">(rangeStart ? "range" : 30);
  const box = useRef<HTMLDivElement>(null);
  // cột đang rê chuột: x = tâm cột, w = bề rộng cột (px trong khung biểu đồ)
  const [hover, setHover] = useState<{ r: Flow; cum: number; x: number; w: number } | null>(null);
  const view = useMemo(() => n === "range" && rangeStart ? rows.filter((r) => r.d >= rangeStart) : rows.slice(-(n === "range" ? 30 : n)),
    [rows, n, rangeStart]);
  const cum = useMemo(() => { let s = 0; return view.map((r) => (s += r.net)); }, [view]);

  useEffect(() => {
    if (!box.current || !view.length) return;
    const muted = css("--muted"), grid = css("--grid"), up = css("--up"), down = css("--down"), accent = css("--accent");
    const chart: IChartApi = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--surface") }, textColor: muted, fontFamily: css("--font") },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false },
      leftPriceScale: { visible: true, borderVisible: false },
      timeScale: { borderColor: grid, fixLeftEdge: true, fixRightEdge: true },
      // tắt đường dóng mặc định: dùng dải nền + tooltip riêng
      crosshair: { vertLine: { visible: false, labelVisible: false }, horzLine: { visible: false, labelVisible: false } },
      handleScroll: false, handleScale: false,
      localization: { locale: "vi-VN", priceFormatter: (p: number) => num(p, Math.abs(p) < 10 ? 1 : 0) },
    });
    const bars = chart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    bars.setData(view.map((r) => ({ time: r.d as Time, value: r.net, color: r.net >= 0 ? up : down })));
    chart.addLineSeries({ priceScaleId: "left", color: accent, lineWidth: 2, lineStyle: LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false })
      .setData(view.map((r, i) => ({ time: r.d as Time, value: cum[i] })));
    chart.timeScale().fitContent();
    const byDay = new Map(view.map((r, i) => [r.d, i]));
    // thời gian dạng "YYYY-MM-DD" được thư viện trả lại thành {year, month, day}
    const iso = (t: Time) => typeof t === "string" ? t : typeof t === "number" ? new Date(t * 1000).toISOString().slice(0, 10)
      : `${t.year}-${String(t.month).padStart(2, "0")}-${String(t.day).padStart(2, "0")}`;
    chart.subscribeCrosshairMove((p) => {
      const i = p.time ? byDay.get(iso(p.time)) : undefined;
      const x = p.time ? chart.timeScale().timeToCoordinate(p.time) : null;
      setHover(i != null && x != null ? { r: view[i], cum: cum[i], x, w: chart.timeScale().options().barSpacing } : null);
    });
    return () => chart.remove();
  }, [view, cum]);

  const name = src === "fx" ? "Khối ngoại" : "Tự doanh CTCK";
  const srcTabs = (
    <div className="tabs" role="tablist" aria-label="Nguồn dòng tiền">
      <button className={src === "fx" ? "on" : ""} onClick={() => setSrc("fx")}>Khối ngoại</button>
      <button className={src === "prop" ? "on" : ""} onClick={() => setSrc("prop")}>Tự doanh</button>
    </div>
  );
  if (!fxRows.length && !(prop ?? []).length && !error) return null;
  if (!rows.length) {
    const err = src === "fx" ? error : propError;
    return <section className="card"><div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{name}</h2>{srcTabs}</div>
      <p className="muted">{err ? `Không tải được dữ liệu ${name.toLowerCase()} (${err}).` : `Chưa có dữ liệu ${name.toLowerCase()} cho mã này.`}</p></section>;
  }

  const buy = view.reduce((s, r) => s + r.buy, 0), sell = view.reduce((s, r) => s + r.sell, 0), net = buy - sell;
  const nUp = view.filter((r) => r.net > 0).length, nDown = view.filter((r) => r.net < 0).length;
  const last = view[view.length - 1];
  const room = last.total_room ? (last.room ?? 0) / last.total_room * 100 : null;
  const short = n === "range" && rangeStart && rows[0].d > rangeStart;   // dữ liệu chưa phủ hết vùng
  const tipW = 220;                                     // bề rộng tooltip; lật sang trái khi sát mép phải

  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div className="row"><h2 style={{ margin: 0 }}>{name} · mua ròng (tỷ đồng)</h2>{srcTabs}</div>
        <div className="tabs">
          {rangeStart && <button className={n === "range" ? "on" : ""} onClick={() => setN("range")}
            title={`Từ đáy vùng Wyckoff (SC ${fullDate(rangeStart)}) tới nay`}>Theo vùng</button>}
          {RANGES.map((x) => (
            <button key={x} className={n === x ? "on" : ""} onClick={() => setN(x)} disabled={rows.length < Math.min(x, 10)}>
              {x} phiên</button>
          ))}
        </div>
      </div>
      <div style={{ position: "relative" }} onMouseLeave={() => setHover(null)}>
        <div ref={box} style={{ width: "100%", height: 240 }} />
        {hover && <>
          <div style={{   // dải nền làm nổi cột đang rê chuột
            position: "absolute", top: 0, bottom: 28, left: hover.x - hover.w / 2, width: Math.max(hover.w, 2),
            background: "var(--muted)", opacity: 0.15, pointerEvents: "none", zIndex: 4,   // trên canvas biểu đồ (z-index 3)
          }} />
          <div className="fx-tip" style={{
            left: Math.max(4, hover.x + hover.w / 2 + tipW + 8 > (box.current?.clientWidth ?? 0)
              ? hover.x - hover.w / 2 - tipW - 6 : hover.x + hover.w / 2 + 6),
            width: tipW,
          }}>
            <div>Ngày: {fullDate(hover.r.d)}</div>
            <div>Giá trị mua ròng: <b className={hover.r.net >= 0 ? "up" : "down"}>{num(hover.r.net, 2)} tỷ</b></div>
            <div className="muted">Mua {num(hover.r.buy, 2)} · bán {num(hover.r.sell, 2)} tỷ</div>
            <div>Lũy kế từ {day(view[0].d)}: <b className={hover.cum >= 0 ? "up" : "down"}>{ty(hover.cum)} tỷ</b></div>
          </div>
        </>}
      </div>
      <dl className="kv" style={{ marginTop: 10, gridTemplateColumns: "auto 1fr auto 1fr" }}>
        <dt>Ròng {view.length} phiên</dt><dd className={net >= 0 ? "up" : "down"}>{ty(net)} tỷ</dd>
        <dt>Mua / bán</dt><dd>{num(buy, 1)} / {num(sell, 1)} tỷ</dd>
        <dt>Phiên mua ròng</dt><dd>{nUp} <span className="muted">· bán ròng {nDown}</span></dd>
        {src === "fx" ? <><dt>Room còn lại</dt><dd>{room == null ? "–" : num(room, 1) + "%"}</dd></>
          : <><dt>Phiên không giao dịch</dt><dd>{view.length - nUp - nDown}</dd></>}
      </dl>
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
        Từ {day(view[0].d)}/{view[0].d.slice(0, 4)} tới {day(last.d)} · cột = mua ròng từng phiên (trục phải), đường xanh = lũy kế
        (trục trái): đi lên đều khi giá ở đáy vùng là dấu hiệu gom, đi xuống khi giá lên gần trần là xả
        · nguồn {src === "fx" ? "VNDirect" : "CafeF (chỉ ~1 năm gần nhất; phiên không giao dịch tính 0)"}
        {short ? ` · dữ liệu ${name.toLowerCase()} chỉ có từ ${fullDate(rows[0].d)}, chưa phủ hết vùng (SC ${fullDate(rangeStart!)})` : ""}
      </p>
    </section>
  );
}
