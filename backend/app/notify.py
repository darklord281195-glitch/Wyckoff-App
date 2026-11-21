"""Gửi tin Telegram (text + ảnh)."""
import httpx
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

API = "https://api.telegram.org/bot{token}/{method}"


def enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_text(text: str):
    # Telegram giới hạn 4096 ký tự/tin -> cắt theo dòng
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > 3900:
            chunks.append(cur); cur = ""
        cur += line
    if cur: chunks.append(cur)
    for ch in chunks:
        r = httpx.post(API.format(token=TELEGRAM_BOT_TOKEN, method="sendMessage"),
                       data=dict(chat_id=TELEGRAM_CHAT_ID, text=ch, disable_web_page_preview="true"), timeout=30)
        r.raise_for_status()


def send_photo(png: bytes, caption: str = ""):
    r = httpx.post(API.format(token=TELEGRAM_BOT_TOKEN, method="sendPhoto"),
                   data=dict(chat_id=TELEGRAM_CHAT_ID, caption=caption[:1000]),
                   files=dict(photo=("chart.png", png, "image/png")), timeout=60)
    r.raise_for_status()
