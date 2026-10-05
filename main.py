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

@app.route('/log')
def view_log():
    try:
        with open("bot_debug.log", "r", encoding="utf-8") as f:
            logs = f.read()
        return f"<h1>Bot CCTV Logs:</h1><pre style='font-size: 15px; color: green;'>{logs}</pre>"
    except Exception as e:
        return f"Log file error: {e}"

# ==========================================
# ২. PYROGRAM BOT
# ==========================================
bot_code = r"""
import os
import sys
import json
import html
import urllib.parse
import asyncio
from datetime import datetime
import requests
import inspect

print("✅ Bot script is starting...", flush=True)

# --- Keep existing Asyncio Event Loop logic intact ---
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
print("✅ Asyncio loop initialized before Pyrogram!", flush=True)
# -----------------------------------------------------

try:
    from pyrogram import Client, filters, enums
    from pyrogram.types import (
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        WebAppInfo,
        CallbackQuery,
        Message
    )
    import firebase_admin
    from firebase_admin import credentials, firestore
    print("✅ Pyrogram & Firebase libraries loaded!", flush=True)
except Exception as e:
    print(f"❌ MODULE ERROR: {e}", flush=True)
    sys.exit(1)

# Ensure InlineKeyboardButton accepts Telegram API 9.4 'style' across all Pyrogram versions
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
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://google.com")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

if BOT_TOKEN:
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
        print("✅ Webhook cleared!", flush=True)
    except Exception as e:
        print(f"⚠️ Could not clear webhook: {e}", flush=True)

bot = Client(":memory:", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

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
    buttons = [
        [InlineKeyboardButton("🖥 Open Web App", web_app=WebAppInfo(url=WEBAPP_URL), style="primary")],
        [
            InlineKeyboardButton("📖 How to Use", callback_data="how_to_use", style="primary"),
            InlineKeyboardButton("🎁 Refer & Earn", callback_data="refer_earn", style="primary")
        ],
        [InlineKeyboardButton("🎧 Support", callback_data="support", style="primary")]
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel", style="primary")])
    return InlineKeyboardMarkup(buttons)

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
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast", style="success"),
            InlineKeyboardButton("💰 Manage Credits", callback_data="admin_credits", style="primary")
        ],
        [InlineKeyboardButton("🚫 Ban / Unban", callback_data="admin_ban_menu", style="danger")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu", style="primary")]
    ])
    return text, keyboard

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
@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user = message.from_user
    if not user:
        return

    if is_user_banned(user.id):
        await message.reply_text("<blockquote><b>⛔ You have been banned from using this bot.</b></blockquote>", parse_mode=enums.ParseMode.HTML)
        return

    user_ref = get_user_ref(user.id)
    user_data = get_user_data(user.id)

    # New user onboarding
    if user_data is None and user_ref:
        referrer_id = None
        if len(message.command) > 1 and message.command[1].isdigit():
            possible_ref = int(message.command[1])
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
                    await client.send_message(
                        chat_id=referrer_id,
                        text=(
                            "<blockquote>"
                            "<b>🎁 REFERRAL BONUS 🎁</b>\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            "ᴀ ɴᴇᴡ ᴜsᴇʀ ᴊᴏɪɴᴇᴅ ᴜsɪɴɢ ʏᴏᴜʀ ʟɪɴᴋ. ʏᴏᴜ ᴇᴀʀɴᴇᴅ <b>+5 ᴄʀᴇᴅɪᴛs</b>!\n"
                            "━━━━━━━━━━━━━━━━━━"
                            "</blockquote>"
                        ),
                        parse_mode=enums.ParseMode.HTML
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
                await client.send_message(chat_id=ADMIN_ID, text=alert_text, parse_mode=enums.ParseMode.HTML)
            except Exception as e:
                print(f"⚠️ Failed to notify admin: {e}", flush=True)

    credits_val = user_data.get("credits", 10) if user_data else 10
    referrals_val = user_data.get("referrals", 0) if user_data else 0

    welcome_text = get_welcome_text(user, credits_val, referrals_val)
    keyboard = build_main_keyboard(user.id)
    await message.reply_text(welcome_text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

# --- TEXT / MEDIA INPUT HANDLER (STATE DISPATCHER) ---
@bot.on_message(filters.private & ~filters.command("start"))
async def message_dispatcher(client: Client, message: Message):
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
                await client.send_message(chat_id=ADMIN_ID, text=alert_text, parse_mode=enums.ParseMode.HTML)
                await client.copy_message(chat_id=ADMIN_ID, from_chat_id=user_id, message_id=message.id)
            except Exception as e:
                print(f"⚠️ Failed to forward user request to admin: {e}", flush=True)

        await message.reply_text(
            (
                "<blockquote>"
                "<b>✅ REQUEST SENT ✅</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssꜰᴜʟʟʏ sᴇɴᴛ ᴛᴏ ᴛʜᴇ ᴀᴅᴍɪɴ!\n\n"
                "👉 <i>ᴘʟᴇᴀsᴇ sᴇɴᴅ /start ᴛᴏ ɢᴏ ʙᴀᴄᴋ ᴛᴏ ᴛʜᴇ ᴍᴀɪɴ ᴍᴇɴᴜ.</i>\n"
                "━━━━━━━━━━━━━━━━━━"
                "</blockquote>"
            ),
            parse_mode=enums.ParseMode.HTML
        )
        return

    back_to_admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="primary")]
    ])

    # 2. ADMIN STATE PROCESSORS
    if user_id == ADMIN_ID and user_id in admin_states:
        state = admin_states.pop(user_id, None)

        # ADMIN BROADCAST
        if state == "broadcast":
            status_msg = await message.reply_text(
                "<blockquote>⏳ <i>Broadcasting message to all users...</i></blockquote>",
                parse_mode=enums.ParseMode.HTML
            )
            users_ref = db.collection("users").stream() if db else []
            sent_count = 0
            failed_count = 0

            for doc in users_ref:
                uid = doc.id
                if not uid.isdigit():
                    continue
                try:
                    await client.copy_message(chat_id=int(uid), from_chat_id=message.chat.id, message_id=message.id)
                    sent_count += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed_count += 1

            await status_msg.edit_text(
                (
                    "<blockquote>"
                    "<b>📢 BROADCAST COMPLETED 📢</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"✅ <b>sᴜᴄᴄᴇssꜰᴜʟʟʏ ᴅᴇʟɪᴠᴇʀᴇᴅ:</b> {sent_count}\n"
                    f"❌ <b>ꜰᴀɪʟᴇᴅ / ʙʟᴏᴄᴋᴇᴅ:</b> {failed_count}\n"
                    "━━━━━━━━━━━━━━━━━━"
                    "</blockquote>"
                ),
                reply_markup=back_to_admin_kb,
                parse_mode=enums.ParseMode.HTML
            )
            return

        # ADMIN BAN USER
        elif state == "ban":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                await message.reply_text("<blockquote>❌ <b>Invalid ID!</b> Please send a numeric User ID.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            if target_ref and target_ref.get().exists:
                target_ref.update({"is_banned": True})
                await message.reply_text(f"<blockquote>✅ User <code>{target_id}</code> has been <b>banned</b>.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text("<blockquote>❌ User not found in database.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            return

        # ADMIN UNBAN USER
        elif state == "unban":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                await message.reply_text("<blockquote>❌ <b>Invalid ID!</b> Please send a numeric User ID.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            if target_ref and target_ref.get().exists:
                target_ref.update({"is_banned": False})
                await message.reply_text(f"<blockquote>✅ User <code>{target_id}</code> has been <b>unbanned</b>.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text("<blockquote>❌ User not found in database.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
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
                    await message.reply_text(f"<blockquote>✅ Credits for user <code>{target_id}</code> updated to <b>{amount}</b>.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)

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
                    req_keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 Send Request", callback_data="user_request", style="success")]
                    ])
                    try:
                        await client.send_message(chat_id=target_id, text=user_alert, reply_markup=req_keyboard, parse_mode=enums.ParseMode.HTML)
                    except Exception as e:
                        print(f"⚠️ Could not notify user {target_id}: {e}", flush=True)
                else:
                    await message.reply_text("<blockquote>❌ User not found in database.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text(
                    (
                        "<blockquote>"
                        "❌ <b>Invalid format!</b> Please provide both User ID and Amount separated by a space.\n"
                        "<i>Example:</i> <code>123456789 50</code>"
                        "</blockquote>"
                    ),
                    reply_markup=back_to_admin_kb,
                    parse_mode=enums.ParseMode.HTML
                )
            return

        # ADMIN RESET CREDITS
        elif state == "reset":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                await message.reply_text("<blockquote>❌ <b>Invalid ID!</b> Please send a numeric User ID.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            target_doc = target_ref.get() if target_ref else None

            if target_doc and target_doc.exists:
                old_credits = target_doc.to_dict().get("credits", 10)
                new_credits = 10
                target_ref.update({"credits": new_credits})
                await message.reply_text(f"<blockquote>🔄 Credits for user <code>{target_id}</code> have been reset to <b>10</b>.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)

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
                req_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Send Request", callback_data="user_request", style="success")]
                ])
                try:
                    await client.send_message(chat_id=target_id, text=user_alert, reply_markup=req_keyboard, parse_mode=enums.ParseMode.HTML)
                except Exception as e:
                    print(f"⚠️ Could not notify user {target_id}: {e}", flush=True)
            else:
                await message.reply_text("<blockquote>❌ User not found in database.</blockquote>", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            return

    if is_user_banned(user_id):
        await message.reply_text("<blockquote><b>⛔ You have been banned from using this bot.</b></blockquote>", parse_mode=enums.ParseMode.HTML)
        return

# --- CALLBACK QUERY NAVIGATION ---
@bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user = query.from_user
    data = query.data

    if is_user_banned(user.id):
        await query.answer("⛔ You are banned from using this bot.", show_alert=True)
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # MAIN MENU
    elif data == "main_menu":
        user_data = get_user_data(user.id)
        credits_val = user_data.get("credits", 10) if user_data else 10
        referrals_val = user_data.get("referrals", 0) if user_data else 0
        text = get_welcome_text(user, credits_val, referrals_val)
        keyboard = build_main_keyboard(user.id)
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

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
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary"),
                InlineKeyboardButton("🎧 Support", callback_data="support", style="primary")
            ]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # REFER & EARN MENU
    elif data == "refer_earn":
        bot_info = await client.get_me()
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
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary"),
                InlineKeyboardButton("↗️ Share with Friends", url=share_url, style="primary")
            ]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # MAIN ADMIN PANEL
    elif data == "admin_panel":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied. Admin only.", show_alert=True)
            return

        admin_states.pop(ADMIN_ID, None)
        text, keyboard = get_admin_panel_components()
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # CANCEL ADMIN ACTION (SMART CANCEL)
    elif data == "admin_cancel":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
            return

        admin_states.pop(ADMIN_ID, None)
        text, keyboard = get_admin_panel_components()
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer("Action cancelled.")

    # ADMIN: BROADCAST INITIATE
    elif data == "admin_broadcast":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # ADMIN: MANAGE CREDITS MENU
    elif data == "admin_credits":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
            return

        text = (
            "<blockquote>"
            "<b>💰 MANAGE CREDITS 💰</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "sᴇʟᴇᴄᴛ ᴀɴ ᴀᴄᴛɪᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴜᴘᴅᴀᴛᴇ ᴏʀ ʀᴇsᴇᴛ ᴜsᴇʀ ᴄʀᴇᴅɪᴛs:\n"
            "━━━━━━━━━━━━━━━━━━"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Add / Edit Credits", callback_data="admin_act_credit", style="success"),
                InlineKeyboardButton("🔄 Reset Credits", callback_data="admin_act_reset", style="danger")
            ],
            [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="primary")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # ADMIN ACTION: ADD / EDIT CREDITS PROMPT
    elif data == "admin_act_credit":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # ADMIN ACTION: RESET CREDITS PROMPT
    elif data == "admin_act_reset":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # ADMIN: BAN / UNBAN MENU
    elif data == "admin_ban_menu":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
            return

        text = (
            "<blockquote>"
            "<b>🚫 BAN / UNBAN USERS 🚫</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "sᴇʟᴇᴄᴛ ᴡʜᴇᴛʜᴇʀ ᴛᴏ ʙᴀɴ ᴏʀ ᴜɴʙᴀɴ ᴀ ᴜsᴇʀ ꜰʀᴏᴍ ᴜsɪɴɢ ᴛʜᴇ ʙᴏᴛ:\n"
            "━━━━━━━━━━━━━━━━━━"
            "</blockquote>"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚫 Ban User", callback_data="admin_act_ban", style="danger"),
                InlineKeyboardButton("✅ Unban User", callback_data="admin_act_unban", style="success")
            ],
            [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="primary")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # ADMIN ACTION: BAN PROMPT
    elif data == "admin_act_ban":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # ADMIN ACTION: UNBAN PROMPT
    elif data == "admin_act_unban":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel", style="danger")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

print("🚀 Starting bot.run()...", flush=True)
bot.run()
"""

with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)

# ফ্লাস্ক ওয়েবসাইট বটকে চালু করে লগ রেকর্ড করবে
log_file = open("bot_debug.log", "w", encoding="utf-8")
subprocess.Popen(["python", "bot.py"], stdout=log_file, stderr=subprocess.STDOUT)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)