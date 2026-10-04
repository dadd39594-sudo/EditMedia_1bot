import os
import threading
import asyncio  # এই মডিউলটি যোগ করা হয়েছে
from flask import Flask, render_template, request, jsonify
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from pyrogram.enums import ParseMode

# ==========================================
# ১. FLASK WEB APP (আসল এডিটর ওয়েবসাইট)
# ==========================================
app = Flask(__name__)

@app.route('/')
def index():
    # এটি আপনার templates/index.html ফাইলটি ওয়েবসাইটের জন্য লোড করবে
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def process_upload():
    # এখানে পরে ImgBB আপলোড এবং ফায়ারবেসের লজিক বসানো হবে
    return jsonify({"success": True, "message": "Website connected!"})

# ==========================================
# ২. PYROGRAM BOT (পাহারাদার বা গেটকিপার)
# ==========================================
API_ID = int(os.getenv("API_ID", "2040"))
API_HASH = os.getenv("API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# রেন্ডার থেকে পাওয়া আপনার ওয়েবসাইটের লিংক
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://google.com") 

bot = Client("GatekeeperBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.command("start") & filters.private)
def start_command(client, message):
    # ওয়েবসাইটের বাটন (Mini App)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥️ Open Editor", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    welcome_msg = (
        "👋 <b>Welcome to EditMedia Pro!</b>\n\n"
        "সব এডিটিং এখন আমাদের নতুন প্রো-ওয়েবসাইটে হবে। নিচে <b>'Open Editor'</b> বাটনে ক্লিক করুন এবং ম্যাজিক দেখুন!"
    )
    message.reply_text(welcome_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)

# ==========================================
# ৩. বট এবং ওয়েবসাইট একসাথে চালানোর ম্যাজিক
# ==========================================
def run_bot():
    # --- ইভেন্ট লুপ এরর ফিক্স ---
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    print("Bot is starting...")
    bot.run()

# ব্যাকগ্রাউন্ডে বট চালু করা হচ্ছে
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
