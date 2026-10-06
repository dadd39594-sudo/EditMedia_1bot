import os
import io
import subprocess
import requests
from PIL import Image
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

# ==========================================
# ১. FLASK WEB APP & BACKEND APIS
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/log')
def view_log():
    try:
        with open("bot_debug.log", "r", encoding="utf-8") as f:
            logs = f.read()
        return f"<h1>Bot CCTV Logs:</h1><pre style='font-size: 15px; color: green;'>{logs}</pre>"
    except Exception as e:
        return f"Log file error: {e}"

# 1. API: Image Upload to ImgBB
@app.route('/api/upload', methods=['POST'])
def process_upload():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        api_key = os.environ.get('IMGBB_API_KEY')
        if not api_key:
            return jsonify({"error": "IMGBB_API_KEY environment variable is not configured"}), 500

        upload_response = requests.post(
            "https://api.imgbb.com/1/upload",
            params={"key": api_key},
            files={"image": (file.filename, file.read(), file.mimetype)}
        )

        res_json = upload_response.json()
        if upload_response.status_code == 200 and res_json.get("success"):
            direct_url = res_json["data"]["url"]
            return jsonify({"url": direct_url})
        else:
            err_msg = res_json.get("error", {}).get("message", "Upload failed")
            return jsonify({"error": err_msg}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 2. API: Resize Image
@app.route('/api/resize', methods=['POST'])
def process_resize():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        width = request.form.get('width', type=int)
        height = request.form.get('height', type=int)

        if not width or not height:
            return jsonify({"error": "Valid width and height (integers) are required"}), 400

        img = Image.open(file.stream)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        resized_img = img.resize((width, height), Image.Resampling.LANCZOS)

        output_io = io.BytesIO()
        resized_img.save(output_io, format='JPEG', quality=95)
        output_io.seek(0)

        return send_file(
            output_io,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name='resized.jpg'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 3. API: Compress Image
@app.route('/api/compress', methods=['POST'])
def process_compress():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        quality = request.form.get('quality', default=60, type=int)

        if quality < 1 or quality > 100:
            return jsonify({"error": "Quality must be between 1 and 100"}), 400

        img = Image.open(file.stream)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        output_io = io.BytesIO()
        img.save(output_io, format='JPEG', optimize=True, quality=quality)
        output_io.seek(0)

        return send_file(
            output_io,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name='compressed.jpg'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 4. API: Convert Image to PDF
@app.route('/api/pdf', methods=['POST'])
def process_pdf():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        img = Image.open(file.stream)

        # Convert to RGB to prevent transparency/alpha channel crashes when saving as PDF
        if img.mode != 'RGB':
            img = img.convert('RGB')

        output_io = io.BytesIO()
        img.save(output_io, format='PDF')
        output_io.seek(0)

        return send_file(
            output_io,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='document.pdf'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# ২. TELEBOT (pyTelegramBotAPI) BOT
# ==========================================
bot_code = r"""
import os
import sys
import json
import html
import urllib.parse
import asyncio
import time
from datetime import datetime
import requests
import inspect

print("✅ Bot script is starting...", flush=True)

# --- Keep existing Asyncio Event Loop logic intact ---
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
print("✅ Asyncio loop initialized before Telebot!", flush=True)
# -----------------------------------------------------

try:
    import telebot
    from telebot.types import (
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        WebAppInfo
    )
    import firebase_admin
    from firebase_admin import credentials, firestore
    print("✅ Telebot & Firebase libraries loaded!", flush=True)
except Exception as e:
    print(f"❌ MODULE ERROR: {e}", flush=True)
    sys.exit(1)

# Ensure InlineKeyboardButton accepts Telegram API 9.4 'style' across all Telebot versions
try:
    _sig = inspect.signature(InlineKeyboardButton.__init__)
    if "style" not in _sig.parameters and not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _sig.parameters.values()):
        _orig_ikb_init = InlineKeyboardButton.__init__
        def _safe_ikb_init(self, *args, **kwargs):
            style = kwargs.pop("style", None)
            _orig_ikb_init(self, *args, **kwargs)
            if style:
                setattr(self, "style", style)
        InlineKeyboardButton.__init__ = _safe_ikb_init
except Exception:
    pass

# Initialize Firebase
try:
    if not firebase_admin._apps:
        firebase_json_str = os.environ.get("FIREBASE_CRED_JSON")
        if firebase_json_str:
            cred_dict = json.loads(firebase_json_str)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
    db = firestore.client()
    print("✅ Firebase initialized successfully!", flush=True)
except Exception as e:
    print(f"⚠️ Firebase initialization failed: {e}", flush=True)
    db = None

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

if BOT_TOKEN:
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
        print("✅ Webhook cleared!", flush=True)
    except Exception as e:
        print(f"⚠️ Could not clear webhook: {e}", flush=True)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# State trackers
admin_states = {}
user_states = {}

# --- HELPER FUNCTIONS ---
def esc(text):
    return html.escape(str(text)) if text else ""

def get_user_ref(user_id):
    if db is None:
        return None
    return db.collection("users").document(str(user_id))

def get_user_data(user_id):
    ref = get_user_ref(user_id)
    if ref:
        doc = ref.get()
        if doc.exists:
            return doc.to_dict()
    return None

def is_user_banned(user_id):
    if user_id == ADMIN_ID:
        return False
    data = get_user_data(user_id)
    return bool(data.get("is_banned", False)) if data else False

def build_main_keyboard(user_id):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🖥 Open Web App", web_app=WebAppInfo(url=WEBAPP_URL), style="primary"))
    markup.row(
        InlineKeyboardButton("📖 How to Use", callback_data="how_to_use", style="primary"),
        InlineKeyboardButton("🎁 Refer & Earn", callback_data="refer_earn", style="primary")
    )
    markup.row(InlineKeyboardButton("🎧 Support", callback_data="support", style="primary"))
    if user_id == ADMIN_ID:
        markup.row(InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel", style="primary"))
    return markup

def get_admin_panel_components():
    total_users = 0
    if db:
        users_docs = db.collection("users").stream()
        total_users = sum(1 for _ in users_docs)

    text = (
        "<blockquote>"
        "<b>⚙️ ADMIN CONTROL PANEL ⚙️</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ᴄᴏɴᴛʀᴏʟ ᴄᴇɴᴛᴇʀ, ʙᴏss!\n"
        "ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴇᴅɪᴛᴍᴇᴅɪᴀ ʙᴏᴛ.\n\n"
        f"📊 <b>ᴛᴏᴛᴀʟ ᴜsᴇʀs:</b> {total_users}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ᴛᴏ ᴍᴀɴᴀɢᴇ:</i>"
        "</blockquote>"
    )
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast", style="success"),
        InlineKeyboardButton("💰 Manage Credits", callback_data="admin_credits", style="primary")
    )
    markup.row(InlineKeyboardButton("🚫 Ban / Unban", callback_data="admin_ban_menu", style="danger"))
    markup.row(InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu", style="primary"))
    return text, markup

def get_welcome_text(user, credits_val, referrals_val):
    full_name = esc(user.first_name + (" " + user.last_name if user.last_name else ""))
    profile = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>Link</a>"
    return (
        "<blockquote>"
        "<b>✨ ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴇᴅɪᴛᴍᴇᴅɪᴀ ʙᴏᴛ ✨</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<i>ʏᴏᴜʀ ᴀʟʟ-ɪɴ-ᴏɴᴇ ᴛᴇʟᴇɢʀᴀᴍ ᴍɪɴɪ ᴀᴘᴘ ꜰᴏʀ sᴍᴀʀᴛ ɪᴍᴀɢᴇ ᴘʀᴏᴄᴇssɪɴɢ. ᴏᴘᴇɴ ᴛʜᴇ ᴡᴇʙ ᴀᴘᴘ ᴛᴏ ᴇᴀsɪʟʏ ɢᴇɴᴇʀᴀᴛᴇ ɪᴍᴀɢᴇ ʟɪɴᴋs, ᴄᴏᴍᴘʀᴇss ᴘʜᴏᴛᴏs, ᴀɴᴅ ᴄᴏɴᴠᴇʀᴛ ɪᴍᴀɢᴇs ᴛᴏ ᴘᴅꜰ ɪɴ sᴇᴄᴏɴᴅs!</i>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>ɴᴀᴍᴇ:</b> {full_name}\n"
        f"🔗 <b>ᴘʀᴏꜰɪʟᴇ:</b> {profile}\n"
        f"🆔 <b>ɪᴅ:</b> <code>{user.id}</code>\n\n"
        f"💰 <b>ᴄʀᴇᴅɪᴛs:</b> {credits_val}\n"
        f"👥 <b>ʀᴇꜰᴇʀʀᴀʟs:</b> {referrals_val}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴇxᴘʟᴏʀᴇ ᴀɴᴅ ɢᴇᴛ sᴛᴀʀᴛᴇᴅ!</i>"
        "</blockquote>"
    )

# --- START COMMAND ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    user = message.from_user
    if not user:
        return

    if is_user_banned(user.id):
        bot.reply_to(message, "<blockquote><b>⛔ You have been banned from using this bot.</b></blockquote>")
        return

    user_ref = get_user_ref(user.id)
    user_data = get_user_data(user.id)

    # New user onboarding
    if user_data is None and user_ref:
        referrer_id = None
        cmd_parts = message.text.split() if message.text else []
        if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
            possible_ref = int(cmd_parts[1])
            if possible_ref != user.id:
                referrer_id = possible_ref

        now_str = datetime.utcnow().strftime("%d %b %Y, %I:%M %p UTC")
        user_data = {
            "id": user.id,
            "name": user.first_name + (" " + user.last_name if user.last_name else ""),
            "username": user.username or "",
            "date": now_str,
            "credits": 10,
            "referrals": 0,
            "referred_by": referrer_id,
            "is_banned": False
        }
        user_ref.set(user_data)

        # Process referral reward
        if referrer_id:
            ref_user_ref = get_user_ref(referrer_id)
            ref_data = get_user_data(referrer_id)
            if ref_data and ref_user_ref:
                ref_user_ref.update({
                    "credits": ref_data.get("credits", 10) + 5,
                    "referrals": ref_data.get("referrals", 0) + 1
                })
                try:
                    bot.send_message(
                        chat_id=referrer_id,
                        text=(
                            "<blockquote>"
                            "<b>🎁 REFERRAL BONUS 🎁</b>\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            "ᴀ ɴᴇᴡ ᴜsᴇʀ ᴊᴏɪɴᴇᴅ ᴜsɪɴɢ ʏᴏᴜʀ ʟɪɴᴋ. ʏᴏᴜ ᴇᴀʀɴᴇᴅ <b>+5 ᴄʀᴇᴅɪᴛs</b>!\n"
                            "━━━━━━━━━━━━━━━━━━"
                            "</blockquote>"
                        )
                    )
                except Exception:
                    pass

        # Send alert to Admin
        if ADMIN_ID != 0:
            profile_link = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>Link</a>"
            alert_text = (
                "<blockquote>"
                "<b>🔔 NEW USER ALERT 🔔</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "ᴀ ɴᴇᴡ ᴜsᴇʀ ʜᴀs ᴊᴜsᴛ sᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ!\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>ɴᴀᴍᴇ:</b> {esc(user_data['name'])}\n"
                f"🔗 <b>ᴘʀᴏꜰɪʟᴇ:</b> {profile_link}\n"
                f"🆔 <b>ɪᴅ:</b> <code>{user.id}</code>\n"
                f"📅 <b>ᴅᴀᴛᴇ:</b> {now_str}\n"
                "━━━━━━━━━━━━━━━━━━"
                "</blockquote>"
            )
            try:
                bot.send_message(chat_id=ADMIN_ID, text=alert_text)
            except Exception as e:
                print(f"⚠️ Failed to notify admin: {e}", flush=True)

    credits_val = user_data.get("credits", 10) if user_data else 10
    referrals_val = user_data.get("referrals", 0) if user_data else 0

    welcome_text = get_welcome_text(user, credits_val, referrals_val)
    keyboard = build_main_keyboard(user.id)
    bot.reply_to(message, welcome_text, reply_markup=keyboard)

# --- TEXT / MEDIA INPUT HANDLER (STATE DISPATCHER) ---
@bot.message_handler(func=lambda message: message.chat.type == 'private')
def message_dispatcher(message):
    user_id = message.from_user.id

    # 1. USER ONE-TIME REQUEST TO ADMIN
    if user_id in user_states and user_states[user_id] == "awaiting_request":
        user_states.pop(user_id, None)
        if ADMIN_ID != 0:
            sender_name = esc(message.from_user.first_name if message.from_user else "User")
            alert_text = (
                "<blockquote>"
                "<b>📩 NEW USER REQUEST 📩</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>ꜰʀᴏᴍ:</b> {sender_name} (<code>{user_id}</code>)\n"
                "━━━━━━━━━━━━━━━━━━"
                "</blockquote>"
            )
            try:
                bot.send_message(chat_id=ADMIN_ID, text=alert_text)
                bot.copy_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=message.message_id)
            except Exception as e:
                print(f"⚠️ Failed to forward user request to admin: {e}", flush=True)

        bot.reply_to(
            message,
            (
                "<blockquote>"
                "<b>✅ REQUEST SENT ✅</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssꜰᴜʟʟʏ sᴇɴᴛ ᴛᴏ ᴛʜᴇ ᴀᴅᴍɪɴ!\n\n"
                "👉 <i>ᴘʟᴇᴀsᴇ sᴇɴᴅ /start ᴛᴏ ɢᴏ ʙᴀᴄᴋ ᴛᴏ ᴛʜᴇ ᴍᴀɪɴ ᴍᴇɴᴜ.</i>\n"
                "━━━━━━━━━━━━━━━━━━"
                "</blockquote>"
            )
        )
        return

    back_to_admin_kb = InlineKeyboardMarkup()
    back_to_admin_kb.row(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="primary"))

    # 2. ADMIN STATE PROCESSORS
    if user_id == ADMIN_ID and user_id in admin_states:
        state = admin_states.pop(user_id, None)

        # ADMIN BROADCAST
        if state == "broadcast":
            status_msg = bot.reply_to(
                message,
                "<blockquote>⏳ <i>Broadcasting message to all users...</i></blockquote>"
            )
            users_ref = db.collection("users").stream() if db else []
            sent_count = 0
            failed_count = 0

            for doc in users_ref:
                uid = doc.id
                if not uid.isdigit():
                    continue
                try:
                    bot.copy_message(chat_id=int(uid), from_chat_id=message.chat.id, message_id=message.message_id)
                    sent_count += 1
                    time.sleep(0.05)
                except Exception:
                    failed_count += 1

            bot.edit_message_text(
                (
                    "<blockquote>"
                    "<b>📢 BROADCAST COMPLETED 📢</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"✅ <b>sᴜᴄᴄᴇssꜰᴜʟʟʏ ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {sent_count}\n"
                    f"❌ <b>ꜰᴀɪʟᴇᴅ / ʙʟᴏᴄᴋᴇᴅ:</b> {failed_count}\n"
                    "━━━━━━━━━━━━━━━━━━"
                    "</blockquote>"
                ),
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                reply_markup=back_to_admin_kb
            )
            return

        # ADMIN BAN USER
        elif state == "ban":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                bot.reply_to(message, "<blockquote>❌ <b>Invalid ID!</b> Please send a numeric User ID.</blockquote>", reply_markup=back_to_admin_kb)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            if target_ref and target_ref.get().exists:
                target_ref.update({"is_banned": True})
                bot.reply_to(message, f"<blockquote>✅ User <code>{target_id}</code> has been <b>banned</b>.</blockquote>", reply_markup=back_to_admin_kb)
            else:
                bot.reply_to(message, "<blockquote>❌ User not found in database.</blockquote>", reply_markup=back_to_admin_kb)
            return

        # ADMIN UNBAN USER
        elif state == "unban":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                bot.reply_to(message, "<blockquote>❌ <b>Invalid ID!</b> Please send a numeric User ID.</blockquote>", reply_markup=back_to_admin_kb)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            if target_ref and target_ref.get().exists:
                target_ref.update({"is_banned": False})
                bot.reply_to(message, f"<blockquote>✅ User <code>{target_id}</code> has been <b>unbanned</b>.</blockquote>", reply_markup=back_to_admin_kb)
            else:
                bot.reply_to(message, "<blockquote>❌ User not found in database.</blockquote>", reply_markup=back_to_admin_kb)
            return

        # ADMIN ADD / EDIT CREDITS
        elif state == "credit":
            parts = message.text.split() if message.text else []
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                target_id = int(parts[0])
                amount = int(parts[1])
                target_ref = get_user_ref(target_id)
                target_doc = target_ref.get() if target_ref else None

                if target_doc and target_doc.exists:
                    old_credits = target_doc.to_dict().get("credits", 10)
                    target_ref.update({"credits": amount})
                    bot.reply_to(message, f"<blockquote>✅ Credits for user <code>{target_id}</code> updated to <b>{amount}</b>.</blockquote>", reply_markup=back_to_admin_kb)

                    # Calculate diff and notify target user
                    diff = amount - old_credits
                    if diff > 0:
                        change_text = f"🎉 <b>+{diff} ᴄʀᴇᴅɪᴛs</b> ʜᴀᴠᴇ ʙᴇᴇɴ ᴀᴅᴅᴇᴅ ᴛᴏ ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ!"
                    elif diff < 0:
                        change_text = f"⚠️ <b>{diff} ᴄʀᴇᴅɪᴛs</b> ʜᴀᴠᴇ ʙᴇᴇɴ ᴅᴇᴅᴜᴄᴛᴇᴅ ꜰʀᴏᴍ ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ."
                    else:
                        change_text = "ℹ️ ʏᴏᴜʀ ᴄʀᴇᴅɪᴛ ʙᴀʟᴀɴᴄᴇ ʜᴀs ʙᴇᴇɴ ᴜᴘᴅᴀᴛᴇᴅ."

                    user_alert = (
                        "<blockquote>"
                        "<b>💰 CREDIT UPDATE ALERT 💰</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        f"{change_text}\n\n"
                        f"💳 <b>ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ:</b> {amount}\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        "<i>ɴᴇᴇᴅ ʜᴇʟᴘ ᴏʀ ᴡᴀɴᴛ ᴛᴏ ʀᴇǫᴜᴇsᴛ ᴄʀᴇᴅɪᴛs? ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ.</i>"
                        "</blockquote>"
                    )
                    req_keyboard = InlineKeyboardMarkup()
                    req_keyboard.row(InlineKeyboardButton("💬 Send Request", callback_data="user_request", style="success"))
                    try:
                        bot.send_message(chat_id=target_id, text=user_alert, reply_markup=req_keyboard)
                    except Exception as e:
                        print(f"⚠️ Could not notify user {target_id}: {e}", flush=True)
                else:
                    bot.reply_to(message, "<blockquote>❌ User not found in database.</blockquote>", reply_markup=back_to_admin_kb)
            else:
                bot.reply_to(
                    message,
                    (
                        "<blockquote>"
                        "❌ <b>Invalid format!</b> Please provide both User ID and Amount separated by a space.\n"
                        "<i>Example:</i> <code>123456789 50</code>"
                        "</blockquote>"
                    ),
                    reply_markup=back_to_admin_kb
                )
            return

        # ADMIN RESET CREDITS
        elif state == "reset":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                bot.reply_to(message, "<blockquote>❌ <b>Invalid ID!</b> Please send a numeric User ID.</blockquote>", reply_markup=back_to_admin_kb)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            target_doc = target_ref.get() if target_ref else None

            if target_doc and target_doc.exists:
                old_credits = target_doc.to_dict().get("credits", 10)
                new_credits = 10
                target_ref.update({"credits": new_credits})
                bot.reply_to(message, f"<blockquote>🔄 Credits for user <code>{target_id}</code> have been reset to <b>10</b>.</blockquote>", reply_markup=back_to_admin_kb)

                # Calculate diff and notify target user
                diff = new_credits - old_credits
                if diff > 0:
                    change_text = f"🎉 <b>+{diff} ᴄʀᴇᴅɪᴛs</b> ʜᴀᴠᴇ ʙᴇᴇɴ ᴀᴅᴅᴇᴅ ᴛᴏ ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ (ʀᴇsᴇᴛ)!"
                elif diff < 0:
                    change_text = f"⚠️ <b>{diff} ᴄʀᴇᴅɪᴛs</b> ʜᴀᴠᴇ ʙᴇᴇɴ ᴅᴇᴅᴜᴄᴛᴇᴅ (ʀᴇsᴇᴛ ᴛᴏ ᴅᴇꜰᴀᴜʟᴛ)."
                else:
                    change_text = "🔄 ʏᴏᴜʀ ᴄʀᴇᴅɪᴛs ʜᴀᴠᴇ ʙᴇᴇɴ ʀᴇsᴇᴛ ᴛᴏ ᴛʜᴇ ᴅᴇꜰᴀᴜʟᴛ ʙᴀʟᴀɴᴄᴇ (10)."

                user_alert = (
                    "<blockquote>"
                    "<b>💰 CREDIT UPDATE ALERT 💰</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"{change_text}\n\n"
                    f"💳 <b>ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ:</b> {new_credits}\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "<i>ɴᴇᴇᴅ ʜᴇʟᴘ ᴏʀ ᴡᴀɴᴛ ᴛᴏ ʀᴇǫᴜᴇsᴛ ᴄʀᴇᴅɪᴛs? ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ.</i>"
                    "</blockquote>"
                )
                req_keyboard = InlineKeyboardMarkup()
                req_keyboard.row(InlineKeyboardButton("💬 Send Request", callback_data="user_request", style="success"))
                try:
                    bot.send_message(chat_id=target_id, text=user_alert, reply_markup=req_keyboard)
                except Exception as e:
                    print(f"⚠️ Could not notify user {target_id}: {e}", flush=True)
            else:
                bot.reply_to(message, "<blockquote>❌ User not found in database.</blockquote>", reply_markup=back_to_admin_kb)
            return

    if is_user_banned(user_id):
        bot.reply_to(message, "<blockquote><b>⛔ You have been banned from using this bot.</b></blockquote>")
        return

# --- CALLBACK QUERY NAVIGATION ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user = call.from_user
    data = call.data
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if is_user_banned(user.id):
        bot.answer_callback_query(call.id, "⛔ You are banned from using this bot.", show_alert=True)
        return

    # USER REQUEST CALLBACK
    if data == "user_request":
        user_states[user.id] = "awaiting_request"
        text = (
            "<blockquote>"
            "<b>💬 SEND A REQUEST 💬</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ᴛʏᴘᴇ ʏᴏᴜʀ ᴍᴇssᴀɢᴇ ʙᴇʟᴏᴡ (ᴇ.ɢ., 'ᴘʟᴇᴀsᴇ ᴀᴅᴅ ᴍᴏʀᴇ ᴄʀᴇᴅɪᴛs') ᴀɴᴅ sᴇɴᴅ ɪᴛ.\n\n"
            "<i>ɪ ᴡɪʟʟ ꜰᴏʀᴡᴀʀᴅ ɪᴛ ᴅɪʀᴇᴄᴛʟʏ ᴛᴏ ᴛʜᴇ ᴀᴅᴍɪɴ.</i>\n"
            "━━━━━━━━━━━━━━━━━━"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # MAIN MENU
    elif data == "main_menu":
        user_data = get_user_data(user.id)
        credits_val = user_data.get("credits", 10) if user_data else 10
        referrals_val = user_data.get("referrals", 0) if user_data else 0
        text = get_welcome_text(user, credits_val, referrals_val)
        keyboard = build_main_keyboard(user.id)
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # HOW TO USE MENU
    elif data == "how_to_use":
        text = (
            "<blockquote>"
            "<b>📖 HOW TO USE EDITMEDIA 📖</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ʏᴏᴜʀ sᴍᴀʀᴛ ɪᴍᴀɢᴇ ᴘʀᴏᴄᴇssɪɴɢ ᴍɪɴɪ ᴀᴘᴘ! ʜᴇʀᴇ ɪs ᴡʜᴀᴛ ʏᴏᴜ ᴄᴀɴ ᴅᴏ ɪɴsɪᴅᴇ ᴏᴜʀ ᴡᴇʙ ᴀᴘᴘ:\n\n"
            "🔹 <b>ꜰᴇᴀᴛᴜʀᴇs:</b>\n"
            "1️⃣ <b>ɪᴍᴀɢᴇ ʟɪɴᴋ ɢᴇɴᴇʀᴀᴛɪᴏɴ:</b> ᴜᴘʟᴏᴀᴅ ᴀɴʏ ᴘʜᴏᴛᴏ ᴀɴᴅ ɢᴇᴛ ᴀ ᴅɪʀᴇᴄᴛ sʜᴀʀᴇᴀʙʟᴇ ʟɪɴᴋ ɪɴsᴛᴀɴᴛʟʏ.\n"
            "2️⃣ <b>ɪᴍᴀɢᴇ ᴄᴏᴍᴘʀᴇssɪᴏɴ:</b> ʀᴇᴅᴜᴄᴇ ᴘʜᴏᴛᴏ ꜰɪʟᴇ sɪᴢᴇs sᴍᴏᴏᴛʜʟʏ ᴡɪᴛʜᴏᴜᴛ ʟᴏsɪɴɢ ᴏʀɪɢɪɴᴀʟ ǫᴜᴀʟɪᴛʏ.\n"
            "3️⃣ <b>ɪᴍᴀɢᴇ ᴛᴏ ᴘᴅꜰ:</b> ᴄᴏɴᴠᴇʀᴛ ʏᴏᴜʀ ɪᴍᴀɢᴇs ɪɴᴛᴏ ʜɪɢʜ-ǫᴜᴀʟɪᴛʏ ᴘᴅꜰ ᴅᴏᴄᴜᴍᴇɴᴛs.\n\n"
            "🪙 <b>ᴀʙᴏᴜᴛ ᴄʀᴇᴅɪᴛs:</b>\n"
            "ʏᴏᴜ ɴᴇᴇᴅ ᴄʀᴇᴅɪᴛs ᴛᴏ ᴜsᴇ ᴛʜᴇsᴇ ᴘʀᴇᴍɪᴜᴍ ꜰᴇᴀᴛᴜʀᴇs. ᴇᴀʀɴ ᴍᴏʀᴇ ᴄʀᴇᴅɪᴛs ʙʏ ʀᴇꜰᴇʀʀɪɴɢ ꜰʀɪᴇɴᴅs!\n"
            "<i>(ɴᴏᴛᴇ: ɪꜰ ʏᴏᴜ ᴀʀᴇ ᴏᴜᴛ ᴏꜰ ᴄʀᴇᴅɪᴛs, ʏᴏᴜ ᴄᴀɴ ᴄᴏɴᴛᴀᴄᴛ ᴛʜᴇ ᴀᴅᴍɪɴ ᴠɪᴀ sᴜᴘᴘᴏʀᴛ ᴛᴏ ᴍᴀɴᴜᴀʟʟʏ ᴀᴅᴅ ᴏʀ ʀᴇsᴇᴛ ʏᴏᴜʀ ᴄʀᴇᴅɪᴛs.)</i>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>ɴᴀᴠɪɢᴀᴛᴇ ʙᴀᴄᴋ ᴏʀ ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ.</i>"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary"),
            InlineKeyboardButton("🎧 Support", callback_data="support", style="primary")
        )
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # REFER & EARN MENU
    elif data == "refer_earn":
        bot_info = bot.get_me()
        user_data = get_user_data(user.id)
        referral_count = user_data.get("referrals", 0) if user_data else 0

        invite_link = f"https://t.me/{bot_info.username}?start={user.id}"
        share_promo_text = (
            "🚀 Check out EDITMEDIA Bot! The best smart image processing Mini App on Telegram.\n"
            "Generate instant image links, compress photos without losing quality, and convert images to PDF in seconds!\n\n"
            f"Join now: {invite_link}"
        )
        encoded_promo = urllib.parse.quote(share_promo_text)
        share_url = f"https://t.me/share/url?url={invite_link}&text={encoded_promo}"

        text = (
            "<blockquote>"
            "<b>🎁 REFER & EARN CREDITS 🎁</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ɪɴᴠɪᴛᴇ ʏᴏᴜʀ ꜰʀɪᴇɴᴅs ᴛᴏ ᴇᴅɪᴛᴍᴇᴅɪᴀ ʙᴏᴛ ᴀɴᴅ ɢᴇᴛ ʀᴇᴡᴀʀᴅᴇᴅ ᴡɪᴛʜ ꜰʀᴇᴇ ᴄʀᴇᴅɪᴛs!\n\n"
            "💰 <b>ʀᴇᴡᴀʀᴅ:</b> ᴇᴀʀɴ <b>5 ᴄʀᴇᴅɪᴛs</b> ꜰᴏʀ ᴇᴠᴇʀʏ ɴᴇᴡ ꜰʀɪᴇɴᴅ ᴡʜᴏ ᴊᴏɪɴs ᴛʜᴇ ʙᴏᴛ ᴜsɪɴɢ ʏᴏᴜʀ ᴜɴɪǫᴜᴇ ɪɴᴠɪᴛᴇ ʟɪɴᴋ.\n\n"
            "🔗 <b>ʏᴏᴜʀ ɪɴᴠɪᴛᴇ ʟɪɴᴋ:</b>\n"
            f"<code>{invite_link}</code>\n\n"
            f"📊 <b>ᴛᴏᴛᴀʟ ʀᴇꜰᴇʀʀᴀʟs:</b> {referral_count}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>sʜᴀʀᴇ ʏᴏᴜʀ ʟɪɴᴋ ᴡɪᴛʜ ꜰʀɪᴇɴᴅs ᴏʀ ɢᴏ ʙᴀᴄᴋ.</i>"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary"),
            InlineKeyboardButton("↗️ Share with Friends", url=share_url, style="primary")
        )
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # SUPPORT MENU
    elif data == "support":
        text = (
            "<blockquote>"
            "<b>📞 SUPPORT & ASSISTANCE 📞</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ɪꜰ ʏᴏᴜ ʜᴀᴠᴇ ᴀɴʏ ᴘʀᴏʙʟᴇᴍs, ʏᴏᴜ ᴄᴀɴ ᴍᴇssᴀɢᴇ ᴍᴇ.\n\n"
            "👤 <b>ᴀᴅᴍɪɴ:</b> @DASFAIRSELLER01\n"
            "🤖 <b>sᴜᴘᴘᴏʀᴛ:</b> @DASASISSTANT_BOT\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>ᴄᴏɴᴛɪɴᴜᴇ ᴡɪᴛʜ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ 👇</i>"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # MAIN ADMIN PANEL
    elif data == "admin_panel":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied. Admin only.", show_alert=True)
            return

        admin_states.pop(ADMIN_ID, None)
        text, keyboard = get_admin_panel_components()
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # CANCEL ADMIN ACTION (SMART CANCEL)
    elif data == "admin_cancel":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied.", show_alert=True)
            return

        admin_states.pop(ADMIN_ID, None)
        text, keyboard = get_admin_panel_components()
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id, "Action cancelled.")

    # ADMIN: BROADCAST INITIATE
    elif data == "admin_broadcast":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied.", show_alert=True)
            return

        admin_states[ADMIN_ID] = "broadcast"
        text = (
            "<blockquote>"
            "<b>📢 BROADCAST MESSAGE 📢</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "sᴇɴᴅ ᴏʀ ꜰᴏʀᴡᴀʀᴅ ᴛʜᴇ ᴍᴇssᴀɢᴇ (ᴛᴇxᴛ, ᴘʜᴏᴛᴏ, ᴠɪᴅᴇᴏ, ᴅᴏᴄᴜᴍᴇɴᴛ) ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʙʀᴏᴀᴅᴄᴀsᴛ ᴛᴏ ᴀʟʟ ʀᴇɢɪsᴛᴇʀᴇᴅ ᴜsᴇʀs.\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>ᴛᴀᴘ ᴄᴀɴᴄᴇʟ ʙᴇʟᴏᴡ ᴛᴏ ᴀʙᴏʀᴛ.</i>"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # ADMIN: MANAGE CREDITS MENU
    elif data == "admin_credits":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied.", show_alert=True)
            return

        text = (
            "<blockquote>"
            "<b>💰 MANAGE CREDITS 💰</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "sᴇʟᴇᴄᴛ ᴀɴ ᴀᴄᴛɪᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴜᴘᴅᴀᴛᴇ ᴏʀ ʀᴇsᴇᴛ ᴜsᴇʀ ᴄʀᴇᴅɪᴛs:\n"
            "━━━━━━━━━━━━━━━━━━"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("➕ Add / Edit Credits", callback_data="admin_act_credit", style="success"),
            InlineKeyboardButton("🔄 Reset Credits", callback_data="admin_act_reset", style="danger")
        )
        keyboard.row(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="primary"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # ADMIN ACTION: ADD / EDIT CREDITS PROMPT
    elif data == "admin_act_credit":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied.", show_alert=True)
            return

        admin_states[ADMIN_ID] = "credit"
        text = (
            "<blockquote>"
            "<b>➕ ADD / EDIT CREDITS ➕</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ <b>ᴜsᴇʀ ɪᴅ</b> ᴀɴᴅ ᴛʜᴇ ɴᴇᴡ <b>ᴄʀᴇᴅɪᴛ ᴀᴍᴏᴜɴᴛ</b> sᴇᴘᴀʀᴀᴛᴇᴅ ʙʏ ᴀ sᴘᴀᴄᴇ.\n\n"
            "<i>ᴇxᴀᴍᴘʟᴇ:</i> <code>123456789 50</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>ᴛᴀᴘ ᴄᴀɴᴄᴇʟ ʙᴇʟᴏᴡ ᴛᴏ ᴀʙᴏʀᴛ.</i>"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # ADMIN ACTION: RESET CREDITS PROMPT
    elif data == "admin_act_reset":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied.", show_alert=True)
            return

        admin_states[ADMIN_ID] = "reset"
        text = (
            "<blockquote>"
            "<b>🔄 RESET CREDITS 🔄</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ <b>ᴜsᴇʀ ɪᴅ</b> ᴡʜᴏsᴇ ᴄʀᴇᴅɪᴛs ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʀᴇsᴇᴛ ᴛᴏ ᴅᴇꜰᴀᴜʟᴛ (10).\n\n"
            "<i>ᴇxᴀᴍᴘʟᴇ:</i> <code>123456789</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>ᴛᴀᴘ ᴄᴀɴᴄᴇʟ ʙᴇʟᴏᴡ ᴛᴏ ᴀʙᴏʀᴛ.</i>"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # ADMIN: BAN / UNBAN MENU
    elif data == "admin_ban_menu":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied.", show_alert=True)
            return

        text = (
            "<blockquote>"
            "<b>🚫 BAN / UNBAN USERS 🚫</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "sᴇʟᴇᴄᴛ ᴡʜᴇᴛʜᴇʀ ᴛᴏ ʙᴀɴ ᴏʀ ᴜɴʙᴀɴ ᴀ ᴜsᴇʀ ꜰʀᴏᴍ ᴜsɪɴɢ ᴛʜᴇ ʙᴏᴛ:\n"
            "━━━━━━━━━━━━━━━━━━"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("🚫 Ban User", callback_data="admin_act_ban", style="danger"),
            InlineKeyboardButton("✅ Unban User", callback_data="admin_act_unban", style="success")
        )
        keyboard.row(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="primary"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # ADMIN ACTION: BAN PROMPT
    elif data == "admin_act_ban":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied.", show_alert=True)
            return

        admin_states[ADMIN_ID] = "ban"
        text = (
            "<blockquote>"
            "<b>🚫 BAN USER 🚫</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ <b>ᴜsᴇʀ ɪᴅ</b> ʏᴏᴜ ᴡɪsʜ ᴛᴏ ʙᴀɴ.\n\n"
            "<i>ᴇxᴀᴍᴘʟᴇ:</i> <code>123456789</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>ᴛᴀᴘ ᴄᴀɴᴄᴇʟ ʙᴇʟᴏᴡ ᴛᴏ ᴀʙᴏʀᴛ.</i>"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

    # ADMIN ACTION: UNBAN PROMPT
    elif data == "admin_act_unban":
        if user.id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Access Denied.", show_alert=True)
            return

        admin_states[ADMIN_ID] = "unban"
        text = (
            "<blockquote>"
            "<b>✅ UNBAN USER ✅</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ <b>ᴜsᴇʀ ɪᴅ</b> ʏᴏᴜ ᴡɪsʜ ᴛᴏ ᴜɴʙᴀɴ.\n\n"
            "<i>ᴇxᴀᴍᴘʟᴇ:</i> <code>123456789</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>ᴛᴀᴘ ᴄᴀɴᴄᴇʟ ʙᴇʟᴏᴡ ᴛᴏ ᴀʙᴏʀᴛ.</i>"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)

print("🚀 Starting bot.infinity_polling()...", flush=True)
bot.infinity_polling()
"""

with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

# ফ্লাস্ক ওয়েবসাইট বটকে চালু করে লগ রেকর্ড করবে
log_file = open("bot_debug.log", "w", encoding="utf-8")
subprocess.Popen(["python", "bot.py"], stdout=log_file, stderr=subprocess.STDOUT)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)