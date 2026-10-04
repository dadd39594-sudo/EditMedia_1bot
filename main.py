import os
import subprocess
import requests
from flask import Flask, render_template, jsonify

# ==========================================
# ১. FLASK WEB APP
# ==========================================
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def process_upload():
    return jsonify({"success": True, "message": "Website connected!"})

# ==========================================
# ২. PYROGRAM BOT (Master Fix)
# ==========================================
bot_code = """
import os
import requests
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from pyrogram.enums import ParseMode

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")

# Purono Webhook Delete kora hocche (Jate bot hang na kore)
if BOT_TOKEN:
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook").json()

bot = Client(":memory:", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.command("start") & filters.private)
def start_command(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥 Open Editor", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    welcome_msg = (
        "👋 <b>Welcome to EditMedia Pro!</b>\\n\\n"
        "সব এডিটিং এখন আমাদের নতুন প্রো-ওয়েবসাইটে হবে। নিচে <b>'Open Editor'</b> বাটনে ক্লিক করুন!"
    )
    message.reply_text(welcome_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)

print("--- BOT IS RUNNING PERFECTLY ---")
bot.run()
"""

# Bot er code ta alada file e save kora hocche
with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

# Bot ke completely alada process e start kora hocche
subprocess.Popen(["python", "bot.py"])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
