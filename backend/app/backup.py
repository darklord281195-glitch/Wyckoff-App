"""Sao lưu phần dữ liệu không tải lại được (danh mục, lịch sử bán, watchlist, phiên đã gửi Telegram, sổ lệnh thử nghiệm) ra JSON.
Giá OHLCV không sao lưu: mất thì tải lại bằng `python -m app.backtest --backfill`.

  .venv\\Scripts\\python -m app.backup                       # ghi backups\\portfolio-YYYYMMDD.json, giữ 30 bản mới nhất
  .venv\\Scripts\\python -m app.backup restore <file.json>   # ghi đè các bảng trên bằng nội dung file
"""
import json, sys, datetime as dt

from .config import ROOT
from .db import connect

TABLES = ("positions", "sales", "watchlist", "telegram_sent", "paper_trades")
DIR = ROOT / "backups"
KEEP = 30


def backup(conn=None, out_dir=DIR):
    conn = conn or connect()
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in TABLES}
    f = out_dir / f"portfolio-{dt.date.today():%Y%m%d}.json"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for old in sorted(out_dir.glob("portfolio-*.json"))[:-KEEP]:
        old.unlink()
    return f


def restore(path, conn=None):
    conn = conn or connect()
    data = json.loads(open(path, encoding="utf-8").read())
    with conn:                                   # một transaction: lỗi giữa chừng thì không mất dữ liệu cũ
        for t in TABLES:
            if t not in data:                    # bản sao lưu cũ chưa có bảng này: giữ nguyên dữ liệu hiện có
                continue
            cols = {c[1] for c in conn.execute(f"PRAGMA table_info({t})")}
            conn.execute(f"DELETE FROM {t}")
            for r in data[t]:
                r = {k: v for k, v in r.items() if k in cols}     # cột thừa từ DB máy khác: bỏ qua
                conn.execute(f"INSERT INTO {t}({','.join(r)}) VALUES ({','.join('?' * len(r))})", tuple(r.values()))


if __name__ == "__main__":
    if sys.argv[1:2] == ["restore"]:
        restore(sys.argv[2]); print("Đã khôi phục từ", sys.argv[2])
    else:
        print("Đã sao lưu:", backup())
