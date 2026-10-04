import os
import threading
import asyncio
import requests
from flask import Flask, render_template, jsonify
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from pyrogram.enums import ParseMode

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
# ২. PYROGRAM BOT (সল্যুশন: Thread-এর ভেতরে)
# ==========================================
def run_bot():
    # ১. থ্রেডের জন্য নতুন ইভেন্ট লুপ তৈরি (Gunicorn-এর আর কোনো সমস্যা হবে না)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # ২. ভেরিয়েবলগুলো নেওয়া
    API_ID = os.environ.get("API_ID")
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

    if not API_ID or not BOT_TOKEN:
        print("ERROR: API_ID or BOT_TOKEN is missing in Render!")
        return

    # ৩. পুরোনো ওয়েবহুক ক্লিয়ার করা (যাতে বট হ্যাং না হয়ে থাকে)
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
    except:
        pass

    # ৪. লুপ সেট করার পর ক্লায়েন্ট তৈরি (এটাই আসল জাদু)
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

    print("--- TELEGRAM BOT IS RUNNING PERFECTLY ---")
    bot.run()

# ফ্লাস্ক চালু হওয়ার সাথে সাথে বট থ্রেড চালু করা হচ্ছে
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
