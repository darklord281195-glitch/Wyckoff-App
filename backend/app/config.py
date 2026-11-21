"""Cấu hình đọc từ D:\\wyckoff-app\\.env"""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]          # D:\wyckoff-app
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("WYCKOFF_DB", ROOT / "backend" / "wyckoff.db"))
LOG_DIR = ROOT / "logs"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Đèn giao thông VNINDEX (điểm): dưới RED = đỏ, trên GREEN = xanh, giữa = vàng
VNI_RED = float(os.getenv("VNI_RED", "1650"))
VNI_GREEN = float(os.getenv("VNI_GREEN", "1781"))

MIN_LIQ_BIL = float(os.getenv("MIN_LIQ_BIL", "10"))   # thanh khoản tối thiểu (tỷ đồng/ngày)
WEB_URL = os.getenv("WEB_URL", "http://localhost:3000")
