"""Định dạng số / ngày kiểu Việt Nam."""
import datetime as dt


def num(x: float, decimals: int = 0) -> str:
    """1688.79 -> '1.688,79' ; 32200 -> '32.200'"""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def price(x: float) -> str:
    """Giá nghìn đồng -> đồng: 12.65 -> '12.650'"""
    return num(round(x * 1000))


def pct(x: float, decimals: int = 1) -> str:
    return ("+" if x > 0 else "") + num(x, decimals) + "%"


def day(d: str) -> str:
    """'2026-10-14' -> '14/10'"""
    return f"{d[8:10]}/{d[5:7]}"


def date_full(d: str) -> str:
    return dt.date.fromisoformat(d).strftime("%d/%m/%Y")
