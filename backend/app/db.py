import sqlite3
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
  sym TEXT NOT NULL, d TEXT NOT NULL,
  o REAL, h REAL, l REAL, c REAL, v REAL,          -- giá nghìn đồng (chỉ số: điểm), KL triệu cp
  PRIMARY KEY (sym, d)
);
CREATE TABLE IF NOT EXISTS scan_results (
  date TEXT NOT NULL, sym TEXT NOT NULL, stage TEXT, data TEXT,
  PRIMARY KEY (date, sym)
);
CREATE TABLE IF NOT EXISTS signals (
  date TEXT NOT NULL, sym TEXT NOT NULL, kind TEXT NOT NULL, is_new INTEGER, text TEXT,
  replay INTEGER DEFAULT 0,                        -- 1 = tạo lại bằng scan --from, 0 = báo thật lúc quét thường
  PRIMARY KEY (date, sym, kind)
);
CREATE TABLE IF NOT EXISTS telegram_sent (        -- phiên đã gửi Telegram: ngày lễ quét lại phiên cũ thì không gửi trùng
  date TEXT PRIMARY KEY, at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS intraday_alerts (      -- cảnh báo giá trong phiên đã gửi: mỗi (ngày, mã, loại) 1 lần
  date TEXT NOT NULL, sym TEXT NOT NULL, kind TEXT NOT NULL, text TEXT, at TEXT, PRIMARY KEY (date, sym, kind)
);
CREATE TABLE IF NOT EXISTS foreign_trade (        -- khối ngoại theo phiên, giá trị tỷ đồng (core/foreign.py)
  sym TEXT NOT NULL, d TEXT NOT NULL, buy REAL, sell REAL, net REAL, net_vol REAL, room REAL, total_room REAL,
  PRIMARY KEY (sym, d)
);
CREATE TABLE IF NOT EXISTS backtest_stats (       -- kết quả backtest theo loại kế hoạch (app.backtest); hit_t1/stop/timeout là %
  plan TEXT PRIMARY KEY, n INTEGER, hit_t1 REAL, stop REAL, timeout REAL, avg_r REAL, ci_lo REAL, ci_hi REAL,
  avg_days REAL, period TEXT, slip REAL, updated TEXT
);
CREATE TABLE IF NOT EXISTS scenario_stats (       -- tỷ lệ 3 kịch bản trên lệnh backtest đã khớp, theo loại kế hoạch × đèn (app.backtest)
  plan TEXT NOT NULL, light TEXT NOT NULL, n INTEGER, up REAL, flat REAL, down REAL, up_days REAL, down_days REAL,
  horizon INTEGER, period TEXT, updated TEXT, avg_r REAL, ci_lo REAL, ci_hi REAL,  -- up/flat/down là %; R TB + KTC95%
  PRIMARY KEY (plan, light)
);
CREATE TABLE IF NOT EXISTS settings (             -- cài đặt người dùng (JSON theo key), vd vốn và ngưỡng rủi ro
  key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS sector_stats (         -- sức mạnh ngành ICB mỗi phiên quét (core/sectors.py)
  date TEXT NOT NULL, icb TEXT NOT NULL, name TEXT, n INTEGER, rs20 REAL, rs60 REAL, pct_d REAL, fx10 REAL,
  PRIMARY KEY (date, icb)
);
CREATE TABLE IF NOT EXISTS backtest_runs (        -- backtest cấp danh mục (portfolio_bt.py): chỉ số + đường vốn theo tuần
  id INTEGER PRIMARY KEY, created TEXT, params TEXT, metrics TEXT, curves TEXT
);
CREATE TABLE IF NOT EXISTS fin_quarter (          -- BCTC quý (core/fundamentals.py), giá trị tỷ đồng; created = ngày công bố
  sym TEXT NOT NULL, fiscal TEXT NOT NULL, created TEXT, item TEXT NOT NULL, value REAL,
  PRIMARY KEY (sym, fiscal, item)
);
CREATE TABLE IF NOT EXISTS fin_meta (             -- lần tải BCTC gần nhất + P/E theo ngày
  sym TEXT PRIMARY KEY, fetched TEXT, pe REAL, mcap REAL, pe_date TEXT
);
CREATE TABLE IF NOT EXISTS paper_trades (         -- sổ lệnh thử nghiệm: app tự "mua" lúc 14h10–14h29 khi đạt kịch bản mua đẹp
  id INTEGER PRIMARY KEY, d TEXT NOT NULL, at TEXT, sym TEXT NOT NULL, kind TEXT,
  entry_px REAL NOT NULL, stop REAL NOT NULL, targets TEXT,   -- targets: JSON [giá T1, T2, ...]; kết quả tính bằng positions.simulate
  light TEXT, rr REAL, vx REAL, close_pos REAL,   -- đèn, lời/lỗ kế hoạch, KL đã khớp / TB20, vị trí giá trong biên độ phiên (0–1)
  why TEXT, plan TEXT,                             -- plan: JSON kế hoạch lúc mua (để phân tích lại điều kiện)
  slip REAL,                                       -- trượt giá mỗi chiều lúc mua (tỷ lệ, costs.slip_for); NULL = mức cố định cũ
  UNIQUE (d, sym)
);
CREATE TABLE IF NOT EXISTS job_runs (             -- mỗi lần chạy tác vụ tự động (scan / auto_buy / backup) cho trang Hệ thống
  id INTEGER PRIMARY KEY, job TEXT NOT NULL, started TEXT, finished TEXT,
  status TEXT,                                     -- ok / skipped (nghỉ lễ) / error
  detail TEXT                                      -- JSON: phiên, số mã, mã lỗi, mã dùng nguồn dự phòng, lỗi...
);
CREATE TABLE IF NOT EXISTS watchlist (
  sym TEXT PRIMARY KEY, note TEXT, added TEXT DEFAULT (date('now'))
);
CREATE TABLE IF NOT EXISTS positions (            -- lệnh đã mua; cắt lỗ + mục tiêu chốt cố định lúc mua
  id INTEGER PRIMARY KEY, sym TEXT NOT NULL, kind TEXT, entry_d TEXT NOT NULL, entry_px REAL NOT NULL,
  qty INTEGER, stop REAL NOT NULL, targets TEXT,  -- targets: JSON [giá T1, T2, ...] (nghìn đồng)
  stop0 REAL,                                      -- cắt lỗ lúc mua (stop có thể bị sửa sau); nhật ký tính R theo stop0
  status TEXT NOT NULL DEFAULT 'open', exit_d TEXT, exit_px REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS sales (                -- từng lần bán thực tế của một lệnh (bán từng phần được)
  id INTEGER PRIMARY KEY, pos_id INTEGER NOT NULL, d TEXT NOT NULL, px REAL NOT NULL, qty INTEGER
);
"""


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """Nâng cấp DB tạo từ bản cũ: thêm cột mới, điền giá trị mặc định."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)")}
    if "stop0" not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN stop0 REAL")
        conn.execute("UPDATE positions SET stop0 = stop WHERE stop0 IS NULL")
        conn.commit()
    ia = {r[1] for r in conn.execute("PRAGMA table_info(intraday_alerts)")}
    if "text" not in ia:                   # nội dung + giờ báo, để trang chủ hiện lại các cảnh báo trong phiên
        conn.execute("ALTER TABLE intraday_alerts ADD COLUMN text TEXT")
        conn.execute("ALTER TABLE intraday_alerts ADD COLUMN at TEXT")
        conn.commit()
    sc = {r[1] for r in conn.execute("PRAGMA table_info(scenario_stats)")}
    if sc and "avg_r" not in sc:           # tỷ lệ kịch bản tính trên lệnh đã khớp: thêm R TB + KTC95%
        for c in ("avg_r", "ci_lo", "ci_hi"):
            conn.execute(f"ALTER TABLE scenario_stats ADD COLUMN {c} REAL")
        conn.commit()
    pt = {r[1] for r in conn.execute("PRAGMA table_info(paper_trades)")}
    if pt and "slip" not in pt:
        conn.execute("ALTER TABLE paper_trades ADD COLUMN slip REAL")
        conn.commit()
    if "replay" not in {r[1] for r in conn.execute("PRAGMA table_info(signals)")}:
        # tín hiệu có trước cột này không biết là báo thật hay tạo lại: coi là tạo lại để không làm đẹp kết quả
        conn.execute("ALTER TABLE signals ADD COLUMN replay INTEGER DEFAULT 0")
        conn.execute("UPDATE signals SET replay = 1")
        conn.commit()
