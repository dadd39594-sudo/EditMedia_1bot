import os
import subprocess
from flask import Flask, render_template, jsonify

# ==========================================
# ১. FLASK WEB APP (শুধুমাত্র ওয়েবসাইট)
# ==========================================
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def process_upload():
    return jsonify({"success": True, "message": "Website connected!"})

# ==========================================
# ২. PYROGRAM BOT (সম্পূর্ণ আলাদা স্ক্রিপ্ট হিসেবে)
# ==========================================
# এই কোডটি মেইন ফাইলে রান হবে না, এটি একটি নতুন ফাইলে সেভ হয়ে আলাদাভাবে চলবে
bot_code = """
import os
import requests
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from pyrogram.enums import ParseMode

API_ID = os.environ.get("API_ID", "2040")
API_HASH = os.environ.get("API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

# পুরোনো ওয়েবহুক ক্লিয়ার করা (যাতে বট হ্যাং না থাকে)
if BOT_TOKEN:
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
    except:
        pass

# মেমরি সেশন ব্যবহার করে বট তৈরি
bot = Client(":memory:", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥 Open Editor", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    welcome_msg = (
        "👋 <b>Welcome to EditMedia Pro!</b>\\n\\n"
        "সব এডিটিং এখন আমাদের নতুন প্রো-ওয়েবসাইটে হবে। নিচে <b>'Open Editor'</b> বাটনে ক্লিক করুন!"
    )
    await message.reply_text(welcome_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)

print("--- 🚀 TELEGRAM BOT IS RUNNING IN SEPARATE PROCESS ---")
bot.run()
"""

# বট কোডটিকে bot.py নামে একটি ফাইলে সেভ করা হচ্ছে
with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

# ফ্লাস্ক চালু হওয়ার আগে আলাদা প্রসেস হিসেবে বটকে চালু করা হচ্ছে
# এতে Gunicorn কোনোভাবেই বটকে ব্লক করতে পারবে না
subprocess.Popen(["python", "bot.py"])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
