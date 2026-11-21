"""Lấy TELEGRAM_CHAT_ID: nhắn một tin bất kỳ cho bot của bạn trên Telegram, rồi chạy
   .venv\\Scripts\\python -m app.telegram_setup
Gửi thử:  .venv\\Scripts\\python -m app.telegram_setup --test
"""
import sys
import httpx
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from . import notify


def main():
    if not TELEGRAM_BOT_TOKEN:
        sys.exit("Chưa có TELEGRAM_BOT_TOKEN trong D:\\wyckoff-app\\.env (tạo bot bằng @BotFather).")
    if "--test" in sys.argv:
        if not TELEGRAM_CHAT_ID:
            sys.exit("Chưa có TELEGRAM_CHAT_ID trong .env")
        notify.send_text("✅ Wyckoff Scanner đã kết nối Telegram thành công.")
        print("Đã gửi tin thử.")
        return
    r = httpx.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", timeout=30).json()
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name") or u["message"]["chat"].get("title")
             for u in r.get("result", []) if "message" in u}
    if not chats:
        sys.exit("Chưa thấy tin nhắn nào. Mở Telegram, nhắn /start cho bot rồi chạy lại.")
    for cid, name in chats.items():
        print(f"TELEGRAM_CHAT_ID={cid}    ({name})")


if __name__ == "__main__":
    main()
