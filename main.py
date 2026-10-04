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
# ২. PYROGRAM BOT (100% Working Async Loop)
# ==========================================
def run_bot():
    # ১. এই থ্রেডের জন্য নতুন ইভেন্ট লুপ তৈরি
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    API_ID = os.environ.get("API_ID")
    API_HASH = os.environ.get("API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

    # পুরোনো ওয়েবহুক ক্লিয়ার (যাতে বট হ্যাং না থাকে)
    try:
        if BOT_TOKEN:
            requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
    except:
        pass

    # বট ক্লায়েন্ট তৈরি
    bot = Client(":memory:", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

    # ২. Pyrogram v2 অনুযায়ী ফাংশন অবশ্যই 'async def' হতে হবে
    @bot.on_message(filters.command("start") & filters.private)
    async def start_command(client, message):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖥 Open Editor", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
        
        welcome_msg = (
            "👋 <b>Welcome to EditMedia Pro!</b>\n\n"
            "সব এডিটিং এখন আমাদের নতুন প্রো-ওয়েবসাইটে হবে। নিচে <b>'Open Editor'</b> বাটনে ক্লিক করুন!"
        )
        # মেসেজ পাঠানোর আগে 'await' দেওয়া বাধ্যতামূলক
        await message.reply_text(welcome_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    # ৩. সিগন্যাল ছাড়াই বটকে জ্যান্ত রাখার আসল ম্যাজিক
    async def start_and_keep_alive():
        await bot.start()
        print("--- 🚀 TELEGRAM BOT IS ALIVE AND LISTENING ---")
        while True:
            await asyncio.sleep(1) # এই অ্যাসিঙ্ক্রোনাস ঘুম বটকে ব্লক করবে না

    # ৪. লুপ চালু করা হলো
    loop.run_until_complete(start_and_keep_alive())

# ফ্লাস্ক চালু হওয়ার সাথে সাথে বট থ্রেড চালু করা হচ্ছে
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
