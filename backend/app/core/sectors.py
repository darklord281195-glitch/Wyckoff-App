"""Sức mạnh ngành ICB tại một phiên quét: trung vị RS20/RS60 của các mã đủ thanh khoản, % mã ở Pha D/sát trần,
tổng khối ngoại 10 phiên. Chỉ để xem bối cảnh: backtest 2019–2026 không thấy lọc theo ngành mạnh giúp chọn mã tốt hơn."""
from statistics import median

MIN_MEMBERS = 3


def sector_stats(results: dict, lst: dict, min_liq: float) -> list[dict]:
    """results: {mã: kết quả analyse đã có rs20/rs60/stage/liq/fx10}; lst: listing (icb, icb_name)."""
    groups = {}
    for s, r in results.items():
        info = lst.get(s) or {}
        if r.get("liq", 0) >= min_liq and info.get("icb"):
            groups.setdefault((info["icb"], info.get("icb_name") or info["icb"]), []).append(r)
    out = []
    for (icb, name), rs in groups.items():
        if len(rs) < MIN_MEMBERS:
            continue
        r20 = [r["rs20"] for r in rs if r.get("rs20") is not None]
        r60 = [r["rs60"] for r in rs if r.get("rs60") is not None]
        fx = [r["fx10"] for r in rs if r.get("fx10") is not None]
        out.append(dict(icb=icb, name=name, n=len(rs),
                        rs20=round(median(r20), 1) if r20 else None, rs60=round(median(r60), 1) if r60 else None,
                        pct_d=round(100 * sum(r.get("stage") in ("D", "near") for r in rs) / len(rs)),
                        fx10=round(sum(fx), 1) if fx else None))
    return sorted(out, key=lambda x: -(x["rs20"] if x["rs20"] is not None else -1e9))


def save(conn, date: str, rows: list[dict]):
    conn.execute("DELETE FROM sector_stats WHERE date=?", (date,))
    conn.executemany("INSERT INTO sector_stats(date,icb,name,n,rs20,rs60,pct_d,fx10) VALUES (?,?,?,?,?,?,?,?)",
                     [(date, r["icb"], r["name"], r["n"], r["rs20"], r["rs60"], r["pct_d"], r["fx10"]) for r in rows])
