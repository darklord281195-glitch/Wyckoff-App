"""Danh sách mã: toàn bộ cổ phiếu niêm yết HOSE + HNX (tự cập nhật hằng tuần, có ngành ICB cấp 2)
+ các nhóm theo dõi tự chọn (đồng bộ skill wyckoff) + watchlist."""
import json, urllib.request, datetime as dt

FINFO = "https://api-finfo.vndirect.com.vn/v4"
HEADERS = {"User-Agent": "Mozilla/5.0"}
FLOORS = ("HOSE", "HNX")

GROUPS = {
    "ck": "SSI VND VCI HCM SHS MBS VIX FTS BSI CTS ORS AGR VDS TVS DSE BVS APG EVS TCI VCK TCX VPX".split(),
    "nh": "VCB BID CTG TCB MBB ACB VPB HDB STB SHB VIB TPB LPB MSB OCB EIB SSB NAB ABB BAB KLB VAB BVB NVB SGB PGB VBB".split(),
    "dtc": "VCG HHV C4G LCG FCN CTD CII KSB VLB DHA PLC HUT CTI DPG HT1 BCC VGC THG CC1 HBC LIG CTR TV2".split(),
    "thep": "HPG HSG NKG TLH POM SMC VGS TVN DTL HMC TIS VCA SHI".split(),
    "bds": ("VHM VIC VRE NVL PDR DIG CEO DXG KDH NLG KBC IDC SZC HDG DXS CII HDC NTL TCH SCR KHG HQC ITA "
            "QCG NBB AGG CRE TDC HPX IJC SJS DPG VPI BCM SIP KOS NHA VCR LHG D2D").split(),
}
GROUP_NAMES = {"ck": "Chứng khoán", "nh": "Ngân hàng", "dtc": "Đầu tư công", "thep": "Thép", "bds": "Bất động sản",
               "wl": "Watchlist"}
INDEX = "VNINDEX"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listing (
  sym TEXT PRIMARY KEY, floor TEXT, name TEXT, icb TEXT, icb_name TEXT, updated TEXT
);
"""


def _get(path):
    req = urllib.request.Request(f"{FINFO}/{path}", headers=HEADERS)
    return json.load(urllib.request.urlopen(req, timeout=30))["data"]


def refresh_listing(conn, max_age_days: int = 7, force: bool = False) -> int:
    """Tải danh sách cổ phiếu niêm yết HOSE+HNX và ngành ICB cấp 2. Chỉ tải lại khi cũ hơn max_age_days."""
    conn.executescript(SCHEMA)
    last = conn.execute("SELECT max(updated) FROM listing").fetchone()[0]
    if not force and last and (dt.date.today() - dt.date.fromisoformat(last)).days < max_age_days:
        return conn.execute("SELECT count(*) FROM listing").fetchone()[0]
    stocks = _get(f"stocks?q=type:stock~status:listed~floor:{','.join(FLOORS)}&size=3000")
    sectors = _get("industry_classification?q=industryLevel:2&size=100")
    icb = {}
    for sec in sectors:
        for code in (sec.get("codeList") or "").split(","):
            icb[code.strip()] = (sec["industryCode"], sec["vietnameseName"])
    today = dt.date.today().isoformat()
    conn.execute("DELETE FROM listing")
    conn.executemany("INSERT INTO listing(sym,floor,name,icb,icb_name,updated) VALUES (?,?,?,?,?,?)",
                     [(s["code"], s["floor"], s.get("shortName") or s.get("companyName"),
                       *icb.get(s["code"], (None, None)), today) for s in stocks if len(s["code"]) == 3])
    conn.commit()
    return len(stocks)


def listing(conn) -> dict[str, dict]:
    conn.executescript(SCHEMA)
    return {r["sym"]: dict(r) for r in conn.execute("SELECT * FROM listing")}


def sectors(conn) -> dict[str, str]:
    """{'icb:8600': 'Bất động sản', ...}"""
    conn.executescript(SCHEMA)
    return {f"icb:{r[0]}": r[1] for r in conn.execute(
        "SELECT DISTINCT icb, icb_name FROM listing WHERE icb IS NOT NULL ORDER BY icb_name")}


def group_of(sym: str, lst: dict | None = None) -> list[str]:
    gs = [g for g, ss in GROUPS.items() if sym in ss]
    if lst and sym in lst and lst[sym].get("icb"):
        gs.append(f"icb:{lst[sym]['icb']}")
    return gs


def watchlist(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT sym FROM watchlist ORDER BY sym")]


def universe(conn, groups=None) -> list[str]:
    """groups=None: toàn bộ HOSE+HNX (+ nhóm theo dõi + watchlist). groups=['ck','bds']: chỉ các nhóm đó."""
    if groups:
        base = [s for g in groups for s in GROUPS.get(g, [])]
    else:
        base = sorted(listing(conn)) or [s for ss in GROUPS.values() for s in ss]
        base += [s for ss in GROUPS.values() for s in ss]          # nhóm theo dõi có mã UPCoM (VCK, TCX...)
    seen, out = set(), []
    for s in base + watchlist(conn):
        if s not in seen:
            seen.add(s); out.append(s)
    return out
