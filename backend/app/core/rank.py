"""Top tiềm năng.

Điểm xếp hạng (từ 28/11/2026, chọn theo kiểm chứng `python -m app.rank_bt` 2019–2026): trong mỗi phiên, các mã đủ
thanh khoản trừ nhóm EXCLUDE_TAGS được xếp phần trăm theo 3 thành phần (FACTORS), điểm % = trung bình 3 thành phần:
  - Cung cạn: KL TB 10 phiên / KL TB 60 phiên càng thấp càng tốt (tinh thần "cạn cung" của Wyckoff);
  - Biến động thấp: độ lệch chuẩn lợi nhuận ngày 20 phiên càng thấp càng tốt;
  - Điểm sẵn sàng của kế hoạch (core/plan.readiness) càng cao càng tốt.
Kiểm chứng (top 10 so với TB mọi mã đủ thanh khoản, 20 phiên): 2019–23 +1,17%, 2024–26 +1,46%; công thức 3 mục cũ
−0,32% / +1,28%. RSI/MACD/khối ngoại đổi chiều giữa hai giai đoạn nên không tính điểm.

3 mục cũ (Wyckoff · Kỹ thuật & Cơ bản · Dòng tiền) vẫn được chấm để hiện tham khảo, KHÔNG tính vào điểm xếp hạng.
Mỗi mục trả dict(score, items); mỗi item dict(key, label, text, pts, max, tone), tone ∈ good / warn / bad / info.

Đây là bảng xếp hạng để tham khảo, KHÔNG phải luật mua: không đổi tín hiệu, luật ẩn theo đèn hay tự mua thử nghiệm.
"""
import datetime as dt
import json
from bisect import bisect_left, bisect_right
from statistics import pstdev

from ..config import MIN_LIQ_BIL
from ..fmt import num, pct, price as _p
from . import fundamentals as fund
from . import mcdx as mcdx_mod
from .foreign import net_sum
from .indicators import rsi, macd, ichimoku
from .proprietary import prop_net

# Điểm xếp hạng: nhóm bị loại (kiểm chứng 2019–2026: kém TB thị trường ở cả hai giai đoạn) và 3 thành phần (khóa, nhãn,
# chiều: −1 = thấp là tốt). Xem docstring.
EXCLUDE_TAGS = ("B/C", "SOS hỏng", "dưới hỗ trợ")
FACTORS = (("dry", "Cung cạn", -1), ("vol", "Biến động thấp", -1), ("ready", "Điểm sẵn sàng", 1))
WEIGHTS = dict(wyckoff=1 / 3, tech=1 / 3, flow=1 / 3)   # 3 mục cũ (chỉ tham khảo, không tính vào điểm xếp hạng)
FX_SCALE = 10       # khối ngoại: mua ròng 20 phiên = ±10% GT giao dịch 20 phiên thì đạt điểm tối đa / tối thiểu
PROP_SCALE = 3      # tự doanh: ±3% (phân bố 27/11/2026: phần lớn trong ±2%; khối ngoại p10/p90 = −13,8% / +6,4%)
MIN_BARS = 80       # ít nến hơn: phần kỹ thuật thiếu dữ liệu cho nửa điểm
INDEX = "VNINDEX"

# Mục 1 – điểm pha Wyckoff theo tag (B/C cộng thêm nếu có Spring/ST gần đây, xem wyckoff_pillar)
PHASE_PTS = {"D-LPS": 40, "D sớm": 36, "D-LPS?": 34, "D-SOS": 30, "sát trần": 28, "B/C": 18,
             "E?": 10, "SOS hỏng": 6, "mới tạo đáy": 4}
MCDX_PTS = {"enter": 20, "lead": 18, "hold": 12, "fade": 7, "spec": 5, "exit": 0, "none": 0}


def _item(key, label, text, pts, mx, tone=None):
    pts = round(pts, 1)
    if tone is None:
        r = pts / mx if mx else 0
        tone = "good" if r >= 0.7 else "warn" if r >= 0.4 else "bad"
    return dict(key=key, label=label, text=text, pts=pts, max=mx, tone=tone)


def _pillar(items, lo=0, hi=100):
    return dict(score=int(round(min(hi, max(lo, sum(x["pts"] for x in items))))), items=items)


def _clamp(x, lo, hi):
    return min(hi, max(lo, x))


def _test_kind(r, p):
    """Spring/ST của kế hoạch Spring/Test (bản quét cũ chưa có test_kind: sự kiện cuối, giống api.scan_latest)."""
    if p.get("test_kind"):
        return p["test_kind"]
    if p.get("kind") == "Spring/Test":
        return next((e["k"] for e in reversed(r.get("events") or []) if e["k"] in ("Spring", "ST")), None)
    return None


def main_target(p: dict) -> dict | None:
    return next((t for t in p.get("targets") or [] if t.get("k") == p.get("main_target")), None)


# ---------------------------------------------------------------- Mục 1: Wyckoff
def wyckoff_pillar(r: dict, stats_by_plan: dict | None = None) -> dict:
    """r: kết quả analyse() hoặc một dòng scan_results. Điểm kẹp trong 0–100."""
    p = r.get("plan") or {}
    tag, c = r.get("tag") or "?", r.get("c")
    items = []
    # pha
    test = _test_kind(r, p)
    if tag == "B/C":
        pts = 18 + (12 if test == "Spring" else 6 if test == "ST" else 0)
        text = "Pha B/C" + (f", có {test} gần đây" if test else "")
    elif tag == "dưới hỗ trợ":
        pts = 12 if p.get("kind") == "Spring/Test" else 8
        text = "dưới hỗ trợ" + (" (kế hoạch Spring/Test)" if pts == 12 else "")
    else:
        pts = PHASE_PTS.get(tag, 10)
        text = tag + (f" · {r['extra']}" if r.get("extra") else "")
    items.append(_item("phase", "Pha", text, pts, 40))
    # điểm sẵn sàng
    ready = (p.get("ready") or {}).get("score")
    rs = ready or 0
    pts = 20 if rs >= 80 else 16 if rs >= 70 else 12 if rs >= 60 else 4
    items.append(_item("ready", "Điểm sẵn sàng", f"{ready}/100" + (" (dưới 60: backtest R TB âm)" if rs < 60 else "")
                       if ready is not None else "chưa có kế hoạch", pts, 20))
    # giá so với vùng vào
    lo, hi, stop = p.get("entry_lo"), p.get("entry_hi"), p.get("stop")
    if not (lo and hi and c):
        pts, text = 0, "không có vùng vào"
    elif p.get("in_zone") or lo <= c <= hi:
        pts, text = 15, f"trong vùng vào {_p(lo)}–{_p(hi)}"
    elif c < lo and (not stop or c > stop):
        pts, text = 10, f"dưới vùng vào {_p(lo)}, trên cắt lỗ"
    elif c > hi and c <= hi * 1.03:
        pts, text = 6, f"trên vùng vào {pct((c / hi - 1) * 100)}"
    else:
        pts, text = 0, (f"cách vùng vào {pct((c / hi - 1) * 100)}" if c > hi else "dưới cắt lỗ")
    items.append(_item("zone", "Giá so với vùng vào", text, pts, 15))
    # lời/lỗ
    rr = p.get("rr")
    pts = 0 if rr is None else 15 if rr >= 3 else 10 if rr >= 2 else 5 if rr >= 1.5 else 0
    items.append(_item("rr", "Lời/lỗ", f"{num(rr, 1)} lần" if rr is not None else "–", pts, 15))
    # dư địa tới mục tiêu chính
    t = main_target(p)
    up = (t["price"] / c - 1) * 100 if t and c else None
    pts = 0 if up is None else 10 if up >= 25 else 7 if up >= 15 else 4 if up >= 8 else 0
    items.append(_item("upside", "Dư địa tới mục tiêu", f"{t['k']} {_p(t['price'])} ({pct(up)})" if up is not None else "–",
                       pts, 10))
    # trừ điểm
    if r.get("lh"):
        items.append(_item("lh", "Đỉnh hạ", f"{len(r['lh'])} đỉnh hạ liên tiếp: cầu yếu", -8, 0, "bad"))
    if r.get("distrib"):
        items.append(_item("distrib", "Phân phối", f"đang có vùng phân phối ({r['distrib'].get('tag')})", -10, 0, "bad"))
    # lịch sử loại kế hoạch (thông tin, 0 điểm)
    kind = (p.get("kind") or "").split(" (")[0]
    st = (stats_by_plan or {}).get(kind)
    if st:
        items.append(_item("plan_stats", "Lịch sử loại kế hoạch",
                           f"{kind}: chạm T1 {num(st['hit_t1'], 1)}% · R TB {'+' if st['avg_r'] > 0 else ''}{num(st['avg_r'], 2)}",
                           0, 0, "info"))
    return _pillar(items)


# ---------------------------------------------------------------- Mục 2: Kỹ thuật & Cơ bản
def fund_part(m: dict | None) -> dict:
    """Cơ bản (tối đa 20), cùng ngưỡng thẻ Cơ bản trên trang mã. Không tính P/E (không có số liệu theo thời điểm)."""
    lv, txt = [], []
    if m:
        if m.get("np_ttm") is not None:
            lv.append("good" if m["np_ttm"] > 0 else "bad"); txt.append(f"lãi 4 quý {num(m['np_ttm'])} tỷ")
        g = m.get("np_growth")
        if g is not None:
            lv.append("good" if g >= 15 or g >= 999 else "mid" if g >= 0 else "bad")
            txt.append("hết lỗ" if g >= 999 else f"tăng {pct(g, 0)}")
        if m.get("roe") is not None:
            lv.append("good" if m["roe"] >= 15 else "mid" if m["roe"] >= 10 else "bad"); txt.append(f"ROE {num(m['roe'], 0)}%")
        if m.get("np_ttm") is not None and m.get("revenue_ttm"):
            mg = m["np_ttm"] / m["revenue_ttm"] * 100
            lv.append("good" if mg >= 15 else "mid" if mg >= 5 else "bad"); txt.append(f"biên {num(mg, 0)}%")
        de = m.get("debt_equity")
        if de is not None and de != 0:
            lv.append("good" if de < 0.5 else "mid" if de <= 1.5 else "bad"); txt.append(f"nợ vay/VCSH {num(de, 1)}")
    if len(lv) < 2:
        return _item("fund", "BCTC", "chưa đủ BCTC", 10, 20, "info")
    pts = 20 * (lv.count("good") + 0.5 * lv.count("mid")) / len(lv)
    return _item("fund", "BCTC", f"{lv.count('good')} tốt · {lv.count('mid')} TB · {lv.count('bad')} yếu ({', '.join(txt)})",
                 pts, 20)


def tech_pillar(bars: list[dict], fund_m: dict | None) -> dict:
    """bars: cửa sổ 500 ngày tính tới phiên đang chấm. 5 phần, mỗi phần tối đa 20."""
    cl = [b["c"] for b in bars]
    short = len(bars) < MIN_BARS
    half = lambda key, label: _item(key, label, "chưa đủ dữ liệu", 10, 20, "info")
    items = []
    # RSI 14
    x = None if short else rsi(cl, 14)[-1]
    if x is None:
        items.append(half("rsi", "RSI 14"))
    else:
        pts, w = ((20, "vùng khỏe") if 50 <= x < 65 else (14, "mạnh, gần quá mua") if 65 <= x < 75 else
                  (12, "trung tính") if 45 <= x < 50 else (6, "quá mua") if x >= 75 else
                  (8, "yếu") if x >= 35 else (4, "quá bán"))
        items.append(_item("rsi", "RSI 14", f"{num(x, 0)} · {w}", pts, 20))
    # MACD 12-26-9
    m = None if short else macd(cl)
    if not m or m["macd"][-1] is None or m["hist"][-2] is None:
        items.append(half("macd", "MACD"))
    else:
        a, s, h, h0 = m["macd"][-1], m["signal"][-1], m["hist"][-1], m["hist"][-2]
        pts = (8 if a > s else 0) + (6 if h > h0 else 0) + (6 if a > 0 else 0)
        w = [("trên" if a > s else "dưới") + " đường tín hiệu", "histogram " + ("tăng" if h > h0 else "giảm"),
             ("trên" if a > 0 else "dưới") + " 0"]
        items.append(_item("macd", "MACD", " · ".join(w), pts, 20))
    # MCDX Plus
    mc = None if short else mcdx_mod.last(cl)
    if not mc:
        items.append(half("mcdx", "MCDX (tay to)"))
    else:
        items.append(_item("mcdx", "MCDX (tay to)", f"{mc['label']} · banker {num(mc['banker'], 0)}%",
                           MCDX_PTS.get(mc["state"], 0), 20))
    # Ichimoku
    ic = None if short else ichimoku(bars)
    n = len(bars)
    if not ic or ic["span_a"][n - 1] is None or ic["span_b"][n - 1] is None or ic["kijun"][-1] is None:
        items.append(half("ichimoku", "Ichimoku"))
    else:
        c = cl[-1]
        top, bot = max(ic["span_a"][n - 1], ic["span_b"][n - 1]), min(ic["span_a"][n - 1], ic["span_b"][n - 1])
        pos, w = (8, "trên mây") if c > top else (4, "trong mây") if c >= bot else (0, "dưới mây")
        tk, kj = ic["tenkan"][-1], ic["kijun"][-1]
        cross, wc = (6, "Tenkan > Kijun") if tk > kj else (3, "Tenkan = Kijun") if tk == kj else (0, "Tenkan < Kijun")
        fa, fb = ic["span_a"][n - 1 + 26], ic["span_b"][n - 1 + 26]
        green = fa is not None and fb is not None and fa > fb
        mom = n > 26 and c > cl[-27]
        pts = pos + cross + (3 if green else 0) + (3 if mom else 0)
        items.append(_item("ichimoku", "Ichimoku", f"{w} · {wc} · mây trước {'xanh' if green else 'đỏ'}"
                           f" · giá {'trên' if mom else 'dưới'} 26 phiên trước", pts, 20))
    items.append(fund_part(fund_m))
    return _pillar(items)


# ---------------------------------------------------------------- Mục 3: Dòng tiền
def _flow_item(key, label, net, net5, liq, scale):
    if net is None or not liq:
        return _item(key, label, "chưa có dữ liệu", 25, 50, "info")
    ratio = net / (liq * 20) * 100
    pts = 25 + 25 * _clamp(ratio / scale, -1, 1)
    tone = "good" if pts >= 30 else "bad" if pts <= 20 else "info"
    text = f"20 phiên {'+' if net > 0 else ''}{num(net, 1)} tỷ ({pct(ratio)} GT)"
    if net5 is not None:
        text += f" · 5 phiên {'+' if net5 > 0 else ''}{num(net5, 1)} tỷ"
    return _item(key, label, text, pts, 50, tone)


def flow_pillar(liq, fx20, fx5, prop: dict | None) -> dict:
    """Khối ngoại (tối đa 50) + tự doanh (tối đa 50): mua ròng 20 phiên so với GT giao dịch 20 phiên."""
    return _pillar([_flow_item("foreign", "Khối ngoại", fx20, fx5, liq, FX_SCALE),
                    _flow_item("prop", "Tự doanh", (prop or {}).get("net"), (prop or {}).get("net5"), liq, PROP_SCALE)])


# ---------------------------------------------------------------- Tổng hợp
def score_symbol(r, bars, fund_m, fx20, fx5, prop, stats_by_plan=None) -> dict:
    pillars = dict(wyckoff=wyckoff_pillar(r, stats_by_plan), tech=tech_pillar(bars, fund_m),
                   flow=flow_pillar(r.get("liq"), fx20, fx5, prop))
    total = int(round(sum(WEIGHTS[k] * v["score"] for k, v in pillars.items())))
    items = [x for v in pillars.values() for x in v["items"]]
    good = sorted([x for x in items if x["tone"] == "good" and x["max"] > 0], key=lambda x: -x["pts"] / x["max"])
    return dict(total=total, pillars=pillars, highlights=good[:3], warnings=[x for x in items if x["tone"] == "bad"])


# ---------------------------------------------------------------- Điểm xếp hạng (3 thành phần)
def factors(r: dict, bars: list[dict]) -> dict:
    """Giá trị thô: dry = KL TB 10 phiên / KL TB 60 phiên, vol = độ lệch chuẩn lợi nhuận ngày 20 phiên (%),
    ready = điểm sẵn sàng của kế hoạch. None khi thiếu dữ liệu."""
    v, cl, n = [b["v"] for b in bars], [b["c"] for b in bars], len(bars)
    v60 = sum(v[-60:]) / 60 if n >= 60 else 0
    rets = [cl[j] / cl[j - 1] - 1 for j in range(max(1, n - 20), n) if cl[j - 1]]
    return dict(dry=round(sum(v[-10:]) / 10 / v60, 3) if v60 else None,
                vol=round(pstdev(rets) * 100, 3) if len(rets) >= 10 else None,
                ready=((r.get("plan") or {}).get("ready") or {}).get("score"))


def pct_scores(raws: list[dict]) -> list[dict]:
    """Điểm phần trăm 0–100 của từng thành phần trong nhóm được xếp cùng phiên (hạng trung bình khi bằng nhau; thiếu
    dữ liệu = 50) và total = TB 3 thành phần, làm tròn."""
    out = [dict() for _ in raws]
    for key, _, sign in FACTORS:
        vals = sorted(sign * x[key] for x in raws if x.get(key) is not None)
        for o, x in zip(out, raws):
            if x.get(key) is None or not vals:
                o[key] = 50.0
                continue
            y = sign * x[key]
            lo, hi = bisect_left(vals, y), bisect_right(vals, y)
            o[key] = round(100 * (lo + (hi - lo) / 2) / len(vals), 1)
    for o in out:
        o["total"] = int(round(sum(o[k] for k, _, _ in FACTORS) / len(FACTORS)))
    return out


def factor_items(raw: dict, sc: dict) -> list[dict]:
    """3 thành phần dạng item (pts = điểm phần trăm, max = 100) để hiện trên trang."""
    text = dict(
        dry=lambda x: f"KL 10 phiên = {num(x, 2)}× TB 60 phiên" + (" (đang cạn)" if x < 0.8 else " (đang tăng)" if x > 1.2 else ""),
        vol=lambda x: f"dao động TB {num(x, 1)}%/phiên trong 20 phiên",
        ready=lambda x: f"{x}/100")
    out = []
    for key, label, _ in FACTORS:
        x, p = raw.get(key), sc[key]
        t = "chưa đủ dữ liệu (tính 50)" if x is None else text[key](x)
        out.append(_item(key, label, f"{t} · hơn {num(p, 0)}% số mã", p, 100))
    return out


def eligible(r: dict) -> bool:
    """Có điểm mua: kế hoạch có vùng vào và cắt lỗ."""
    p = r.get("plan") or {}
    return bool(p.get("entry_hi") and p.get("stop"))


def bars_until(conn, sym: str, d: str, days: int = 500) -> list[dict]:
    """Nến trong (d − days ngày, d], giống cửa sổ 500 ngày của scan.py."""
    since = (dt.date.fromisoformat(d) - dt.timedelta(days=days)).isoformat()
    return [dict(x) for x in conn.execute("SELECT d,o,h,l,c,v FROM ohlcv WHERE sym=? AND d>? AND d<=? ORDER BY d",
                                          (sym, since, d))]


def plan_stats(conn) -> dict:
    """{loại kế hoạch: dict(n, hit_t1, avg_r)} từ backtest_stats."""
    try:
        return {x["plan"]: dict(n=x["n"], hit_t1=x["hit_t1"], avg_r=x["avg_r"])
                for x in conn.execute("SELECT plan, n, hit_t1, avg_r FROM backtest_stats")}
    except Exception:
        return {}


def _sort_key(x):
    """Nhóm được xếp trước (điểm giảm dần, rồi cung cạn), nhóm bị loại cuối bảng."""
    return (x["excluded"], -(x["total"] or 0), -((x.get("parts") or {}).get("dry") or 0), x["sym"])


LIGHT_WARN = {"red": "Đèn đỏ: luật app không mở lệnh mới", "yellow": "Đèn vàng: luật app ẩn LPS/D sớm"}


def rank(conn, d: str, min_liq: float = MIN_LIQ_BIL, light: str | None = None) -> list[dict]:
    """Chấm mọi mã của phiên quét d có GT TB20 ≥ min_liq (bỏ VNINDEX). Mã thuộc EXCLUDE_TAGS: excluded=True, không có
    điểm, đứng cuối. Còn lại: điểm % = TB phần trăm 3 thành phần trong nhóm; 3 mục cũ ở `pillars` chỉ để tham khảo."""
    from ..universe import listing
    lst, stats = listing(conn), plan_stats(conn)
    rows = []
    for sym, data in conn.execute("SELECT sym, data FROM scan_results WHERE date=? AND sym<>?", (d, INDEX)).fetchall():
        r = json.loads(data)
        if not r or (r.get("liq") or 0) < min_liq:
            continue
        fm = fund.metrics_at(fund.load(conn, sym), d)
        bars = bars_until(conn, sym, d)
        s = score_symbol(r, bars, fm, net_sum(conn, sym, d, 20), net_sum(conn, sym, d, 5), prop_net(conn, sym, d), stats)
        # cảnh báo: chỉ phần trừ điểm của Wyckoff (đỉnh hạ, phân phối) + đèn; RSI/MACD/khối ngoại không còn tính điểm
        s["warnings"] = [x for x in s["pillars"]["wyckoff"]["items"] if x["tone"] == "bad" and x["key"] in ("lh", "distrib")]
        p, info = r.get("plan") or {}, lst.get(sym) or {}
        t = main_target(p)
        ok = eligible(r)
        if light == "red":
            s["warnings"].append(_item("light", "Đèn", LIGHT_WARN["red"], 0, 0, "bad"))
        elif light == "yellow" and ((r.get("tag") or "").startswith("D-LPS") or r.get("tag") == "D sớm"):
            s["warnings"].append(_item("light", "Đèn", LIGHT_WARN["yellow"], 0, 0, "bad"))
        rows.append(dict(sym=sym, name=info.get("name"), icb_name=info.get("icb_name"), floor=info.get("floor"),
                         c=r.get("c"), chg=r.get("chg"), tag=r.get("tag"), stage=r.get("stage"), plan_kind=p.get("kind"),
                         entry_lo=p.get("entry_lo"), entry_hi=p.get("entry_hi"), stop=p.get("stop"), rr=p.get("rr"),
                         in_zone=p.get("in_zone"),
                         target=dict(k=t["k"], price=t["price"], upside=round((t["price"] / r["c"] - 1) * 100, 1))
                         if t and r.get("c") else None,
                         liq=r.get("liq"), eligible=ok, excluded=r.get("tag") in EXCLUDE_TAGS, raw=factors(r, bars),
                         ref_total=s["total"], pillars=s["pillars"], warnings=s["warnings"], highlights=[],
                         total=None, parts=None, factors=[]))
    pool = [x for x in rows if not x["excluded"]]
    for x, sc in zip(pool, pct_scores([x["raw"] for x in pool])):
        x["total"], x["parts"] = sc["total"], {k: sc[k] for k, _, _ in FACTORS}
        x["factors"] = factor_items(x["raw"], sc)
        x["highlights"] = [it for it in x["factors"] if it["tone"] == "good"]
    rows.sort(key=_sort_key)
    el = [x["total"] for x in pool]
    for x in rows:
        x["pct_rank"] = round(100 * sum(v < x["total"] for v in el) / len(el)) if el and x["total"] is not None else None
    return rows


# ---------------------------------------------------------------- Lưu mỗi phiên + thay đổi
def save_daily(conn, d: str, light: str | None = None) -> list[dict]:
    """Chấm phiên d (GT ≥ MIN_LIQ_BIL) và ghi đè snapshot của phiên đó vào rank_daily (chỉ nhóm được xếp; cột w/t/f
    = phần trăm cung cạn / biến động thấp / sẵn sàng). Trả mọi dòng đã chấm."""
    rows = rank(conn, d, MIN_LIQ_BIL, light)
    conn.execute("DELETE FROM rank_daily WHERE date=?", (d,))
    conn.executemany("INSERT INTO rank_daily(date,sym,total,w,t,f,eligible) VALUES (?,?,?,?,?,?,?)",
                     [(d, x["sym"], x["total"], round(x["parts"]["dry"]), round(x["parts"]["vol"]),
                       round(x["parts"]["ready"]), int(x["eligible"])) for x in rows if not x["excluded"]])
    conn.commit()
    return rows


def compare_date(conn, d: str, vs: str = "prev") -> str | None:
    """Phiên để so sánh: 'prev' = phiên quét gần nhất trước d; 'week' = phiên quét thứ 5 trước d
    (không đủ thì phiên cũ nhất có). None nếu không có phiên nào trước d."""
    k = 5 if vs == "week" else 1
    ds = [x[0] for x in conn.execute("SELECT DISTINCT date FROM scan_results WHERE date<? ORDER BY date DESC LIMIT ?",
                                     (d, k))]
    return ds[-1] if ds else None


def order(rows: list[dict], eligible_only: bool = False) -> list[dict]:
    """Nhóm được xếp (bỏ EXCLUDE_TAGS), theo thứ tự của rows; eligible_only: chỉ mã có điểm mua."""
    return [x for x in rows if not x["excluded"] and (x["eligible"] or not eligible_only)]


def positions_of(rows: list[dict], eligible_only: bool = False) -> dict:
    """{mã: hạng (từ 1)} theo thứ tự của rows (đã sắp xếp)."""
    return {x["sym"]: i for i, x in enumerate(order(rows, eligible_only), 1)}


def positions(conn, d: str, min_liq: float = MIN_LIQ_BIL, eligible_only: bool = False, rows=None) -> dict:
    """{mã: hạng} phiên d: từ rank_daily nếu có (và min_liq = MIN_LIQ_BIL), không thì chấm lại (hoặc dùng rows đã chấm)."""
    if rows is None and min_liq == MIN_LIQ_BIL:
        q = "SELECT sym FROM rank_daily WHERE date=?" + (" AND eligible=1" if eligible_only else "") + \
            " ORDER BY total DESC, w DESC, sym"
        got = [x[0] for x in conn.execute(q, (d,))]
        if got:
            return {s: i for i, s in enumerate(got, 1)}
    return positions_of(rows if rows is not None else rank(conn, d, min_liq), eligible_only)


def changes(cur_rows: list[dict], prev_pos: dict, n: int, eligible_only: bool = False) -> list[dict]:
    """Gắn prev_pos / new (không nằm trong top n trước đó) vào từng dòng của cur_rows (mọi mã đủ thanh khoản, đã sắp
    xếp). Trả các mã rời top n: dict(sym, prev_pos, pos, total) hoặc dict(sym, prev_pos, reason)."""
    ordered = order(cur_rows, eligible_only)
    for x in ordered:
        x["prev_pos"] = prev_pos.get(x["sym"])
        x["new"] = bool(prev_pos) and (x["prev_pos"] is None or x["prev_pos"] > n)
    top = {x["sym"] for x in ordered[:n]}
    pos = {x["sym"]: (i, x) for i, x in enumerate(ordered, 1)}
    every = {x["sym"]: x for x in cur_rows}
    dropped = []
    for s, p in sorted(prev_pos.items(), key=lambda kv: kv[1]):
        if p > n or s in top:
            continue
        if s in pos:
            dropped.append(dict(sym=s, prev_pos=p, pos=pos[s][0], total=pos[s][1]["total"]))
        else:
            why = ("không còn đủ thanh khoản" if s not in every else f"nay ở nhóm loại ({every[s]['tag']})"
                   if every[s]["excluded"] else "không còn điểm mua")
            dropped.append(dict(sym=s, prev_pos=p, reason=why))
    return dropped


def in_top(conn, d: str, n: int = 10, last: int = 20) -> tuple[dict, int]:
    """({mã: số phiên nằm trong top n}, số phiên đã xét): tối đa `last` snapshot ≤ d."""
    ds = [x[0] for x in conn.execute("SELECT DISTINCT date FROM rank_daily WHERE date<=? ORDER BY date DESC LIMIT ?",
                                     (d, last))]
    cnt: dict = {}
    for day in ds:
        for (s,) in conn.execute("SELECT sym FROM rank_daily WHERE date=? ORDER BY total DESC, w DESC, sym LIMIT ?",
                                 (day, n)):
            cnt[s] = cnt.get(s, 0) + 1
    return cnt, len(ds)


def daily_top(conn, d: str, light: str | None, n: int = 10) -> dict:
    """Sau lần quét: lưu snapshot phiên d, trả top n (cờ new so với phiên trước) + các mã rời top."""
    rows = save_daily(conn, d, light)
    prev = compare_date(conn, d, "prev")
    prev_pos = positions(conn, prev) if prev else {}
    dropped = changes(rows, prev_pos, n)
    return dict(date=d, light=light, prev=prev, rows=order(rows)[:n], dropped=dropped)


def light_at(conn, d: str) -> str | None:
    """Đèn thị trường của phiên quét d (từ dòng VNINDEX trong scan_results), như api.market."""
    from .market import traffic_light
    row = conn.execute("SELECT data FROM scan_results WHERE sym=? AND date=?", (INDEX, d)).fetchone()
    res = json.loads(row[0]) if row else None
    return traffic_light(res, res and res.get("breadth"))["light"] if res else None


def backfill_daily(conn, log=print) -> int:
    """Ghi snapshot rank_daily cho mọi phiên đã có trong scan_results mà chưa có snapshot (tăng dần). Trả số phiên."""
    have = {x[0] for x in conn.execute("SELECT DISTINCT date FROM rank_daily")}
    todo = [x[0] for x in conn.execute("SELECT DISTINCT date FROM scan_results ORDER BY date") if x[0] not in have]
    for d in todo:
        rows = save_daily(conn, d, light_at(conn, d))
        log(f"{d}: {len(rows)} mã đủ thanh khoản · {sum(not x['excluded'] for x in rows)} mã được xếp")
    return len(todo)
