import os
import subprocess
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# ==========================================
# ১. FLASK WEB APP
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def process_upload():
    return jsonify({"success": True, "message": "Website connected!"})

@app.route('/log')
def view_log():
    try:
        with open("bot_debug.log", "r", encoding="utf-8") as f:
            logs = f.read()
        return f"<h1>Bot CCTV Logs:</h1><pre style='font-size: 15px; color: green;'>{logs}</pre>"
    except Exception as e:
        return f"Log file error: {e}"

# ==========================================
# ২. PYROGRAM BOT (সল্যুশন সহ)
# ==========================================
bot_code = """
import os
import sys
import requests
import asyncio

print("✅ Bot script is starting...", flush=True)

# --- আসল ম্যাজিক: Pyrogram লোড হওয়ার আগেই ইভেন্ট লুপ তৈরি ---
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
print("✅ Asyncio loop initialized before Pyrogram!", flush=True)
# -------------------------------------------------------------

# এবার Pyrogram শান্তি মতো লোড হবে
try:
    from pyrogram import Client, filters
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    print("✅ Pyrogram imported successfully!", flush=True)
except Exception as e:
    print(f"❌ MODULE ERROR: {e}", flush=True)
    sys.exit(1)

try:
    API_ID = os.environ.get("API_ID")
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

    if BOT_TOKEN:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
        print("✅ Webhook cleared!", flush=True)

    bot = Client(":memory:", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

    @bot.on_message(filters.command("start"))
    async def start_command(client, message):
        print(f"📥 Received /start from user: {message.from_user.id}", flush=True)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖥 Open Editor", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
        await message.reply_text("👋 Welcome to EditMedia Pro!", reply_markup=keyboard)
        print("📤 Reply sent successfully!", flush=True)

    print("🚀 Starting bot.run()...", flush=True)
    bot.run()
except Exception as e:
    print(f"❌ CRITICAL ERROR: {e}", flush=True)
"""

with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

# ফ্লাস্ক ওয়েবসাইট বটকে চালু করে লগ রেকর্ড করবে
log_file = open("bot_debug.log", "w", encoding="utf-8")
subprocess.Popen(["python", "bot.py"], stdout=log_file, stderr=subprocess.STDOUT)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
