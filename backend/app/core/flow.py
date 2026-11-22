"""Dòng tiền giữa các ngành ICB: tỷ trọng giá trị giao dịch (KL × giá) của ngành trong toàn thị trường.

Tỷ trọng tăng = tiền đang dồn vào ngành, giảm = tiền rút ra. Giá trị giao dịch tăng chưa chắc là tiền vào (có thể là
bị bán mạnh), nên đọc cùng với giá của ngành (bình quân theo giá trị giao dịch) và khối ngoại:
  tỷ trọng tăng + giá tăng = tiền vào · tỷ trọng tăng + giá giảm = bị xả · tỷ trọng giảm + giá tăng = tăng thiếu lực ·
  tỷ trọng giảm + giá giảm = tiền rút ra.
v trong ohlcv là triệu cp, c là nghìn đồng -> v × c = tỷ đồng."""
from collections import defaultdict

INDEX = "VNINDEX"
MIN_SHARE = 0.3          # ngành có tỷ trọng dưới mức này (%) ở cả hai kỳ: quá nhỏ, bỏ khỏi biểu đồ
WEEKS = 12               # số tuần (khối 5 phiên) cho bản đồ nhiệt


def _label(d_share, ret):
    if d_share >= 0:
        return "Tiền vào" if ret >= 0 else "Bị xả"
    return "Tăng thiếu lực" if ret >= 0 else "Tiền rút ra"


def sector_flow(conn, short: int = 5, long: int = 20, end: str | None = None) -> dict:
    """So kỳ gần (short phiên tới `end`) với kỳ trước đó (long phiên liền trước)."""
    q = f"SELECT d, c FROM ohlcv WHERE sym=?{' AND d<=?' if end else ''} ORDER BY d DESC LIMIT ?"
    need = max(short + long, WEEKS * 5) + 1
    idx = conn.execute(q, (INDEX, end, need) if end else (INDEX, need)).fetchall()[::-1]
    if len(idx) < short + long + 1:
        return dict(rows=[], heat=[], error="Chưa đủ dữ liệu giá")
    days = [r[0] for r in idx]
    idx_c = {r[0]: r[1] for r in idx}
    now, prev = days[-short:], days[-short - long:-short]
    base = days[-short - 1]                       # giá tham chiếu: phiên ngay trước kỳ gần
    rows = conn.execute("""SELECT o.sym, o.d, o.c, o.v, l.icb, l.icb_name FROM ohlcv o JOIN listing l ON l.sym = o.sym
                           WHERE o.d >= ? AND o.d <= ? AND l.icb IS NOT NULL""", (days[0], days[-1])).fetchall()
    val = defaultdict(lambda: defaultdict(float))            # ngành -> ngày -> tỷ đồng
    px = defaultdict(dict)                                   # mã -> ngày -> giá
    name, members = {}, defaultdict(set)
    for sym, d, c, v, icb, nm in rows:
        val[icb][d] += (v or 0) * (c or 0)
        px[sym][d] = c
        name[icb] = nm
        members[icb].add(sym)
    tot = defaultdict(float)
    for icb in val:
        for d, x in val[icb].items():
            tot[d] += x
    share = lambda icb, ds: 100 * sum(val[icb].get(d, 0) for d in ds) / (sum(tot[d] for d in ds) or 1)
    sym_val = defaultdict(float)
    for sym, d, c, v, *_ in rows:
        if d in now:
            sym_val[sym] += (v or 0) * (c or 0)
    fx = dict(conn.execute(f"""SELECT l.icb, SUM(f.net) FROM foreign_trade f JOIN listing l ON l.sym = f.sym
                               WHERE f.d >= ? AND f.d <= ? GROUP BY l.icb""", (now[0], now[-1])).fetchall())
    idx_ret = (idx_c[now[-1]] / idx_c[base] - 1) * 100
    out = []
    for icb in val:
        a, b = share(icb, now), share(icb, prev)
        if a < MIN_SHARE and b < MIN_SHARE:
            continue
        # giá ngành: bình quân lợi nhuận các mã trong kỳ gần, trọng số = giá trị giao dịch của mã trong kỳ đó
        w = r = 0.0
        tops = []
        for s in members[icb]:
            p0, p1 = px[s].get(base), px[s].get(now[-1])
            if p0 and p1 and sym_val[s] > 0:
                ret = (p1 / p0 - 1) * 100
                w += sym_val[s]; r += sym_val[s] * ret
                tops.append((sym_val[s], s, round(ret, 1)))
        ret = r / w if w else 0.0
        v_now = sum(val[icb].get(d, 0) for d in now) / short
        v_prev = sum(val[icb].get(d, 0) for d in prev) / long
        out.append(dict(icb=icb, name=name[icb], share=round(a, 2), share_prev=round(b, 2), d_share=round(a - b, 2),
                        value=round(v_now), value_prev=round(v_prev), value_chg=round((v_now / v_prev - 1) * 100, 1) if v_prev else None,
                        ret=round(ret, 2), rel=round(ret - idx_ret, 2), fx=round(fx[icb], 1) if fx.get(icb) is not None else None,
                        label=_label(a - b, ret - idx_ret),
                        top=[dict(sym=s, value=round(x), ret=rt) for x, s, rt in sorted(tops, reverse=True)[:3]]))
    out.sort(key=lambda x: -x["d_share"])
    # bản đồ nhiệt: tỷ trọng mỗi tuần (khối 5 phiên) trừ tỷ trọng bình quân 12 tuần của chính ngành đó (điểm %)
    blocks = [days[len(days) - 5 * (i + 1):len(days) - 5 * i] for i in range(WEEKS) if len(days) >= 5 * (i + 1)][::-1]
    heat = []
    for x in out:
        sh = [share(x["icb"], b) for b in blocks]
        avg = sum(sh) / len(sh) if sh else 0
        heat.append(dict(icb=x["icb"], name=x["name"], cells=[round(s - avg, 2) for s in sh]))
    total_now = sum(tot[d] for d in now) / short
    total_prev = sum(tot[d] for d in prev) / long
    return dict(end=now[-1], start=now[0], prev_start=prev[0], prev_end=prev[-1], short=short, long=long,
                total=round(total_now), total_prev=round(total_prev), idx_ret=round(idx_ret, 2),
                rows=out, weeks=[b[-1] for b in blocks], heat=heat)
