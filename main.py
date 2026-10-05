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
bot_code = """
import os
import sys
import html
import urllib.parse
import asyncio
from datetime import datetime
import requests

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
    from firebase_admin import firestore
    print("✅ Pyrogram & Firebase libraries loaded!", flush=True)
except Exception as e:
    print(f"❌ MODULE ERROR: {e}", flush=True)
    sys.exit(1)

# Initialize Firebase
try:
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()
    print("✅ Firebase initialized successfully!", flush=True)
except Exception as e:
    print(f"⚠️ Firebase initialization warning: {e}", flush=True)
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

# State tracker for admin button inputs
admin_states = {}

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
        [InlineKeyboardButton("🖥 Open Web App", web_app=WebAppInfo(url=WEBAPP_URL))],
        [
            InlineKeyboardButton("📖 How to Use", callback_data="how_to_use"),
            InlineKeyboardButton("🎁 Refer & Earn", callback_data="refer_earn")
        ],
        [InlineKeyboardButton("🎧 Support", callback_data="support")]
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_admin_panel_components():
    total_users = 0
    if db:
        users_docs = db.collection("users").stream()
        total_users = sum(1 for _ in users_docs)

    text = (
        "<b>⚙️ ADMIN CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Welcome to the control center, Boss!\n"
        "Here you can manage your EDITMEDIA Bot.\n\n"
        f"📊 <b>Total Users:</b> {total_users}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>Select an option to manage:</i>"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("💰 Manage Credits", callback_data="admin_credits")
        ],
        [InlineKeyboardButton("🚫 Ban / Unban", callback_data="admin_ban_menu")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    ])
    return text, keyboard

def get_welcome_text(user, credits_val, referrals_val):
    full_name = esc(user.first_name + (" " + user.last_name if user.last_name else ""))
    profile = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>Link</a>"
    return (
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>✨ WELCOME TO EDITMEDIA BOT ✨</b>\n"
        "<i>Your all-in-one Telegram Mini App for smart image processing. Open the Web App to easily generate image links, compress photos, and convert images to PDF in seconds!</i>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Name:</b> {full_name}\n"
        f"🔗 <b>Profile:</b> {profile}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n\n"
        f"💰 <b>Credits:</b> {credits_val}\n"
        f"👥 <b>Referrals:</b> {referrals_val}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>Tap the buttons below to explore and get started!</i>"
    )

# --- START COMMAND ---
@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user = message.from_user
    if not user:
        return

    if is_user_banned(user.id):
        await message.reply_text("<b>⛔ You have been banned from using this bot.</b>", parse_mode=enums.ParseMode.HTML)
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
                        text="<b>🎁 Referral Bonus!</b>\nA new user joined using your link. You earned <b>+5 Credits</b>!",
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception:
                    pass

        # Send alert to Admin
        if ADMIN_ID != 0:
            profile_link = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>Link</a>"
            alert_text = (
                "<b>🔔 NEW USER ALERT 🔔</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "A new user has just started the bot!\n"
                f"👤 <b>Name:</b> {esc(user_data['name'])}\n"
                f"🔗 <b>Profile:</b> {profile_link}\n"
                f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
                f"📅 <b>Date:</b> {now_str}\n"
                "━━━━━━━━━━━━━━━━━━"
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
    back_to_admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]
    ])

    if user_id == ADMIN_ID and user_id in admin_states:
        state = admin_states.pop(user_id, None)

        # 1. BROADCAST
        if state == "broadcast":
            status_msg = await message.reply_text(
                "⏳ <i>Broadcasting message to all users...</i>",
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
                f"<b>📢 Broadcast Completed!</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"✅ <b>Successfully Delivered:</b> {sent_count}\n"
                f"❌ <b>Failed / Blocked:</b> {failed_count}",
                reply_markup=back_to_admin_kb,
                parse_mode=enums.ParseMode.HTML
            )
            return

        # 2. BAN USER
        elif state == "ban":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                await message.reply_text("❌ <b>Invalid ID!</b> Please send a numeric User ID.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            if target_ref and target_ref.get().exists:
                target_ref.update({"is_banned": True})
                await message.reply_text(f"✅ User <code>{target_id}</code> has been <b>banned</b>.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text("❌ User not found in database.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            return

        # 3. UNBAN USER
        elif state == "unban":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                await message.reply_text("❌ <b>Invalid ID!</b> Please send a numeric User ID.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            if target_ref and target_ref.get().exists:
                target_ref.update({"is_banned": False})
                await message.reply_text(f"✅ User <code>{target_id}</code> has been <b>unbanned</b>.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text("❌ User not found in database.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            return

        # 4. ADD / EDIT CREDITS
        elif state == "credit":
            parts = message.text.split() if message.text else []
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                target_id = int(parts[0])
                amount = int(parts[1])
                target_ref = get_user_ref(target_id)
                if target_ref and target_ref.get().exists:
                    target_ref.update({"credits": amount})
                    await message.reply_text(f"✅ Credits for user <code>{target_id}</code> updated to <b>{amount}</b>.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
                else:
                    await message.reply_text("❌ User not found in database.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text(
                    "❌ <b>Invalid format!</b> Please provide both User ID and Amount separated by a space.\n<i>Example:</i> <code>123456789 50</code>",
                    reply_markup=back_to_admin_kb,
                    parse_mode=enums.ParseMode.HTML
                )
            return

        # 5. RESET CREDITS
        elif state == "reset":
            text_val = message.text.strip() if message.text else ""
            if not text_val.isdigit():
                await message.reply_text("❌ <b>Invalid ID!</b> Please send a numeric User ID.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
                return
            target_id = int(text_val)
            target_ref = get_user_ref(target_id)
            if target_ref and target_ref.get().exists:
                target_ref.update({"credits": 10})
                await message.reply_text(f"🔄 Credits for user <code>{target_id}</code> have been reset to <b>10</b>.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await message.reply_text("❌ User not found in database.", reply_markup=back_to_admin_kb, parse_mode=enums.ParseMode.HTML)
            return

    if is_user_banned(user_id):
        await message.reply_text("<b>⛔ You have been banned from using this bot.</b>", parse_mode=enums.ParseMode.HTML)
        return

# --- CALLBACK QUERY NAVIGATION ---
@bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user = query.from_user
    data = query.data

    if is_user_banned(user.id):
        await query.answer("⛔ You are banned from using this bot.", show_alert=True)
        return

    # MAIN MENU
    if data == "main_menu":
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
            "<b>📖 HOW TO USE EDITMEDIA</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Welcome to your smart Image Processing Mini App! Here is what you can do inside our Web App:\n\n"
            "🔹 <b>Features:</b>\n"
            "1️⃣ <b>Image Link Generation:</b> Upload any photo and get a direct shareable link instantly.\n"
            "2️⃣ <b>Image Compression:</b> Reduce photo file sizes smoothly without losing original quality.\n"
            "3️⃣ <b>Image to PDF:</b> Convert your images into high-quality PDF documents.\n\n"
            "🪙 <b>About Credits:</b>\n"
            "You need Credits to use these premium features. Earn more credits by referring friends!\n"
            "<i>(Note: If you are out of credits, you can contact the Admin via Support to manually add or reset your credits.)</i>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>Navigate back or contact support.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="main_menu"),
                InlineKeyboardButton("🎧 Support", callback_data="support")
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
            "<b>🎁 REFER & EARN CREDITS</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Invite your friends to EDITMEDIA Bot and get rewarded with free credits!\n\n"
            "💰 <b>Reward:</b> Earn <b>5 Credits</b> for every new friend who joins the bot using your unique invite link.\n\n"
            "🔗 <b>Your Invite Link:</b>\n"
            f"<code>{invite_link}</code>\n\n"
            f"📊 <b>Total Referrals:</b> {referral_count}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>Share your link with friends or go back.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="main_menu"),
                InlineKeyboardButton("↗️ Share with Friends", url=share_url)
            ]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # SUPPORT MENU
    elif data == "support":
        text = (
            "📞 sᴜᴘᴘᴏʀᴛ & ᴀssɪsᴛᴀɴᴄᴇ\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ɪғ ʏᴏᴜ ʜᴀᴠᴇ ᴀɴʏ ᴘʀᴏʙʟᴇᴍs, ʏᴏᴜ ᴄᴀɴ ᴍᴇssᴀɢᴇ ᴍᴇ.\n\n"
            "👤 ᴀᴅᴍɪɴ: @DASFAIRSELLER01\n"
            "🤖 sᴜᴘᴘᴏʀᴛ: @DASASISSTANT_BOT\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ᴄᴏɴᴛɪɴᴜᴇ ᴡɪᴛʜ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ 👇"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
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
            "<b>📢 BROADCAST MESSAGE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Send or forward the message (Text, Photo, Video, Document) you want to broadcast to all registered users.\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>Tap cancel below to abort.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # ADMIN: MANAGE CREDITS MENU
    elif data == "admin_credits":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
            return

        text = (
            "<b>💰 MANAGE CREDITS</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Select an action below to update or reset user credits:\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Add / Edit Credits", callback_data="admin_act_credit"),
                InlineKeyboardButton("🔄 Reset Credits", callback_data="admin_act_reset")
            ],
            [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]
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
            "<b>➕ ADD / EDIT CREDITS</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Please send the <b>User ID</b> and the new <b>Credit Amount</b> separated by a space.\n\n"
            "<i>Example:</i> <code>123456789 50</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>Tap cancel below to abort.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
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
            "<b>🔄 RESET CREDITS</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Please send the <b>User ID</b> whose credits you want to reset to default (10).\n\n"
            "<i>Example:</i> <code>123456789</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>Tap cancel below to abort.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer()

    # ADMIN: BAN / UNBAN MENU
    elif data == "admin_ban_menu":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
            return

        text = (
            "<b>🚫 BAN / UNBAN USERS</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Select whether to ban or unban a user from using the bot:\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚫 Ban User", callback_data="admin_act_ban"),
                InlineKeyboardButton("✅ Unban User", callback_data="admin_act_unban")
            ],
            [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]
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
            "<b>🚫 BAN USER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Please send the <b>User ID</b> you wish to ban.\n\n"
            "<i>Example:</i> <code>123456789</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>Tap cancel below to abort.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
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
            "<b>✅ UNBAN USER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Please send the <b>User ID</b> you wish to unban.\n\n"
            "<i>Example:</i> <code>123456789</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 <i>Tap cancel below to abort.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
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