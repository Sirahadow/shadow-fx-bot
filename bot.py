import os
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def test_telegram():
    if not TOKEN or not CHAT_ID:
        print("ERROR: Telegram Secrets missing!")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": "SHADOW FX BOT: Telegram connection is working! 🚀"
    }

    try:
        response = requests.post(url, data=data, timeout=20)
        print(response.status_code)
        print(response.json())

    except Exception as error:
        print("Telegram Error:", error)

if __name__ == "__main__":
    test_telegram()
