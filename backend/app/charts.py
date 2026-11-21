"""Vẽ ảnh PNG biểu đồ Wyckoff (nến + KL + vùng SC–AR + chấm sự kiện) để gửi Telegram."""
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd


def render_png(sym: str, R: list[dict], res: dict, days: int = 160, unit_pt: bool = False) -> bytes:
    rows = R[-days:]
    df = pd.DataFrame(rows).rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    df.index = pd.DatetimeIndex(df["d"]); df = df.drop(columns=["d"])
    style = mpf.make_mpf_style(base_mpf_style="yahoo", gridstyle=":", facecolor="white",
                               marketcolors=mpf.make_marketcolors(up="#14966a", down="#d2453b", inherit=True))
    fig, axes = mpf.plot(df, type="candle", volume=True, style=style, returnfig=True, figsize=(10, 5.6),
                         tight_layout=True, xrotation=0, datetime_format="%d/%m",
                         ylabel="Điểm" if unit_pt else "Giá (nghìn đ)", ylabel_lower="KL (triệu cp)")
    ax = axes[0]
    first = rows[0]["d"]
    xpos = {r["d"]: i for i, r in enumerate(rows)}
    rg = res.get("range")
    if rg:
        x0 = xpos.get(rg["start"], 0) if rg["start"] >= first else 0
        ax.axhspan(rg["sup"], rg["res"], xmin=x0 / len(rows), color="#3d55c9", alpha=0.07)
        for y, lab in ((rg["res"], "AR"), (rg["sup"], "SC")):
            ax.axhline(y, color="#3d55c9", lw=1, ls="--", alpha=0.8)
            ax.text(len(rows) - 1, y, f" {lab} {y:.2f}", color="#3d55c9", fontsize=8, va="bottom", ha="right")
    span = df["High"].max() - df["Low"].min()
    ax.set_ylim(df["Low"].min() - span * 0.14, df["High"].max() + span * 0.14)
    for e in key_events(res.get("events", [])):
        if e["d"] not in xpos: continue
        x = xpos[e["d"]]; hi = e["pos"] == "high"
        y = e["price"] + (span * 0.04 if hi else -span * 0.04)
        ax.plot(x, y, "o", color="#3d55c9", ms=5)
        ax.annotate(e["k"], (x, y), textcoords="offset points", xytext=(0, 8 if hi else -14),
                    ha="center", fontsize=8, fontweight="bold")
    fig.suptitle(f"{sym} · {res.get('tag', '')} · {res.get('d', '')}", fontsize=12, x=0.02, ha="left")
    fig.subplots_adjust(top=0.92)
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=110, bbox_inches="tight"); plt.close(fig)
    return buf.getvalue()


def key_events(events: list[dict]) -> list[dict]:
    """Bớt nhiễu: chỉ giữ ST/Spring thấp nhất và gần nhất."""
    tests = [e for e in events if e["k"] in ("ST", "Spring")]
    keep = {id(min(tests, key=lambda e: e["price"])), id(tests[-1])} if tests else set()
    return [e for e in events if e["k"] not in ("ST", "Spring") or id(e) in keep]
