import os
import threading
import time
import requests
from flask import Flask, render_template, jsonify

# ==========================================
# ১. FLASK WEB APP (আসল এডিটর ওয়েবসাইট)
# ==========================================
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def process_upload():
    return jsonify({"success": True, "message": "Website connected!"})

# ==========================================
# ২. PYROGRAM BOT (বিনা signal-এ চালানোর ম্যাজিক)
# ==========================================
def run_bot():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    from pyrogram import Client, filters
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    from pyrogram.enums import ParseMode

    API_ID = os.environ.get("API_ID")
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

    # পুরোনো ওয়েবহুক ক্লিয়ার করা
    try:
        if BOT_TOKEN:
            requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
    except:
        pass

    bot = Client(":memory:", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

    @bot.on_message(filters.command("start") & filters.private)
    def start_command(client, message):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖥 Open Editor", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
        
        welcome_msg = (
            "👋 <b>Welcome to EditMedia Pro!</b>\n\n"
            "সব এডিটিং এখন আমাদের নতুন প্রো-ওয়েবসাইটে হবে। নিচে <b>'Open Editor'</b> বাটনে ক্লিক করুন!"
        )
        message.reply_text(welcome_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    # ম্যাজিক: bot.run() এর বদলে bot.start() ব্যবহার করছি যাতে signal error না আসে
    bot.start()
    print("--- TELEGRAM BOT IS RUNNING PERFECTLY ---")
    
    # থ্রেডটাকে বাঁচিয়ে রাখার জন্য ম্যানুয়াল ইনফিনিট লুপ
    while True:
        time.sleep(1)

# ফ্লাস্ক চালু হওয়ার সাথে সাথে বট থ্রেড চালু করা হচ্ছে
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
