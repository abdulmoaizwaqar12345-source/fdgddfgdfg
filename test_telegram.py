"""
Run this once, locally, after you've created your Telegram bot and set
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID as environment variables, to confirm
you receive a test message on your phone.

Usage (Mac/Linux):
    export TELEGRAM_BOT_TOKEN="123456:ABC-your-token"
    export TELEGRAM_CHAT_ID="123456789"
    python3 test_telegram.py

Usage (Windows PowerShell):
    $env:TELEGRAM_BOT_TOKEN="123456:ABC-your-token"
    $env:TELEGRAM_CHAT_ID="123456789"
    python3 test_telegram.py
"""
import os
import requests

token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

if not token or not chat_id:
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables first.")

url = f"https://api.telegram.org/bot{token}/sendMessage"
resp = requests.post(url, json={
    "chat_id": chat_id,
    "text": "✅ Your forex alert bot is connected. Setup alerts will look like this.",
})

print("Status:", resp.status_code)
print("Response:", resp.text)
