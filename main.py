import os
import sys
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
        return f"<h1>Bot CCTV Logs:</h1><pre style='font-size: 16px; color: green;'>{logs}</pre>"
    except Exception as e:
        return f"Log file is not ready yet. Please refresh after 10 seconds. Error: {e}"

# ==========================================
# ৩. PYROGRAM BOT (সম্পূর্ণ আলাদা স্ক্রিপ্ট)
# ==========================================
bot_code = """
import os
import logging
import requests
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# বটের প্রতিটি কাজের রেকর্ড রাখা হচ্ছে
logging.basicConfig(
    filename='bot_debug.log', 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("✅ Bot script started successfully!")

try:
    API_ID = os.environ.get("API_ID")
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

    logging.info(f"API_ID Found: {'Yes' if API_ID else 'No'}")
    logging.info(f"API_HASH Found: {'Yes' if API_HASH else 'No'}")
    logging.info(f"BOT_TOKEN Found: {'Yes' if BOT_TOKEN else 'No'}")

    if BOT_TOKEN:
        res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook").json()
        logging.info(f"Webhook Status: {res}")

    bot = Client(":memory:", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

    @bot.on_message(filters.command("start"))
    async def start_command(client, message):
        logging.info(f"📥 Received /start from user: {message.from_user.id}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖥 Open Editor", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
        await message.reply_text("👋 Welcome to EditMedia Pro!", reply_markup=keyboard)
        logging.info("📤 Reply sent successfully!")

    logging.info("🚀 Starting bot.run()...")
    bot.run()
except Exception as e:
    logging.error(f"❌ CRITICAL ERROR: {e}")
"""

with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

# রেন্ডারের একদম সঠিক পাইথন ইঞ্জিন দিয়ে বট চালু করা
subprocess.Popen([sys.executable, "bot.py"])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
