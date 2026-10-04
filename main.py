import os
import subprocess
import asyncio
from flask import Flask, render_template, request, jsonify

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
# ২. PYROGRAM BOT (আলাদা ফাইলে চালানোর জন্য তৈরি)
# ==========================================
bot_code = """
import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from pyrogram.enums import ParseMode

API_ID = int(os.environ.get("API_ID", "2040"))
API_HASH = os.environ.get("API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

bot = Client("GatekeeperBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.command("start") & filters.private)
def start_command(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥 Open Editor", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    welcome_msg = (
        "👋 <b>Welcome to EditMedia Pro!</b>\\n\\n"
        "সব এডিটিং এখন আমাদের নতুন প্রো-ওয়েবসাইটে হবে। নিচে <b>'Open Editor'</b> বাটনে ক্লিক করুন এবং ম্যাজিক দেখুন!"
    )
    message.reply_text(welcome_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)

print("Starting Bot Process...")
bot.run()
"""

# বট কোডটিকে একটি আলাদা ফাইলে সেভ করা হচ্ছে
with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

# ==========================================
# ৩. বট এবং ওয়েবসাইট একসাথে চালানোর ম্যাজিক (Subprocess)
# ==========================================
def run_bot_process():
    # সম্পূর্ণ আলাদা প্রসেস হিসেবে বটকে রান করানো
    subprocess.Popen(["python", "bot.py"])

# ফ্লাস্ক স্টার্ট হওয়ার আগে বট প্রসেস চালু করা
run_bot_process()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
