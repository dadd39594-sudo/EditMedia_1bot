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

# ==========================================
# ২. সিসিটিভি ক্যামেরা (লগ দেখার জন্য)
# ==========================================
@app.route('/log')
def view_log():
    try:
        with open("bot_debug.log", "r", encoding="utf-8") as f:
            logs = f.read()
        return f"<h1>Bot CCTV Logs:</h1><pre style='font-size: 15px; color: red;'>{logs}</pre>"
    except Exception as e:
        return f"Log file error: {e}"

# ==========================================
# ৩. PYROGRAM BOT (লগ ট্র্যাপ সহ)
# ==========================================
bot_code = """
import os
import requests
import sys

print("✅ Bot script is starting...", flush=True)

try:
    from pyrogram import Client, filters
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    print("✅ Pyrogram imported successfully!", flush=True)
except ImportError as e:
    print(f"❌ MODULE ERROR: {e}", flush=True)
    sys.exit(1)

try:
    API_ID = os.environ.get("API_ID")
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

    print(f"API_ID Found: {'Yes' if API_ID else 'No'}", flush=True)
    print(f"API_HASH Found: {'Yes' if API_HASH else 'No'}", flush=True)
    print(f"BOT_TOKEN Found: {'Yes' if BOT_TOKEN else 'No'}", flush=True)

    if BOT_TOKEN:
        res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook").json()
        print(f"Webhook Status: {res}", flush=True)

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

# বট ফাইলটি তৈরি করা হচ্ছে
with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

# ফ্লাস্ক ওয়েবসাইটই লগ ফাইল তৈরি করে বটের সমস্ত আউটপুট সেখানে রেকর্ড করবে
log_file = open("bot_debug.log", "w", encoding="utf-8")
subprocess.Popen(["python", "bot.py"], stdout=log_file, stderr=subprocess.STDOUT)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
