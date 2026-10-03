import asyncio
import os
import json
import logging
from typing import Dict, List, Optional, Tuple

# --- CRITICAL: Python 3.14 Loop Fix ---
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# --------------------------------------

import aiohttp
from aiohttp import web
from pyrogram import Client, filters, idle, errors
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
    InputMediaPhoto,
    InputMediaDocument
)
from pyrogram.errors import UserNotParticipant
from PIL import Image
import firebase_admin
from firebase_admin import credentials, db

# Logging Configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Environment Variables
API_ID = int(os.getenv("API_ID", "2040"))
API_HASH = os.getenv("API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
FIREBASE_JSON = os.getenv("FIREBASE_JSON", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")  
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNELS = [ch.strip() for ch in os.getenv("CHANNELS", "").split(",") if ch.strip()]
PORT = int(os.getenv("PORT", 8080))

BOT_USERNAME = "EditMediaBot"

# State Constants
STATE_NONE = 0
STATE_WAITING_PHOTO = 1
STATE_WAITING_RESIZE_CUSTOM = 2
STATE_ADMIN_BROADCAST = 3
STATE_ADMIN_BAN = 4
STATE_ADMIN_UNBAN = 5
STATE_ADMIN_ADD_CREDIT = 6
STATE_ADMIN_RESET_CREDIT = 7

# Memory tracker for transient states and tasks
USER_STATES: Dict[int, dict] = {}

# --- FIREBASE SETUP ---
try:
    if FIREBASE_JSON:
        cert_dict = json.loads(FIREBASE_JSON)
        cred = credentials.Certificate(cert_dict)
        db_url = DATABASE_URL or cert_dict.get('databaseURL') or f"https://{cert_dict['project_id']}-default-rtdb.firebaseio.com/"
        firebase_admin.initialize_app(cred, {'databaseURL': db_url})
        logger.info(f"Firebase successfully initialized with URL: {db_url}")
    else:
        logger.warning("FIREBASE_JSON missing. Database features will be disabled.")
except Exception as e:
    logger.error(f"CRITICAL FIREBASE INIT ERROR: {e}")

# --- FIREBASE VERSION HISTORY & UNDO/REDO HELPERS ---

def get_session(user_id: int) -> Optional[dict]:
    """Retrieves the full session (history and step) from Firebase."""
    try:
        if firebase_admin._apps:
            return db.reference(f"users/{user_id}/session").get()
    except Exception as e:
        logger.error(f"Error fetching session for {user_id}: {e}")
    return None

def get_current_active_file(user_id: int) -> Optional[dict]:
    """Gets the file data for the current step."""
    session = get_session(user_id)
    if session and "file_history" in session:
        history = session["file_history"]
        step = session.get("current_step", 0)
        if 0 <= step < len(history):
            return history[step]
    return None

def set_new_session(user_id: int, file_dict: dict):
    """Initializes a new session history for an uploaded file."""
    try:
        if firebase_admin._apps:
            db.reference(f"users/{user_id}/session").set({
                "file_history": [file_dict],
                "current_step": 0
            })
    except Exception as e:
        logger.error(f"Error creating session for {user_id}: {e}")

def push_new_version(user_id: int, file_dict: dict) -> Tuple[int, int]:
    """Truncates future redo steps and appends a new file version."""
    try:
        if firebase_admin._apps:
            ref = db.reference(f"users/{user_id}/session")
            session = ref.get() or {"file_history": [], "current_step": -1}
            history = session.get("file_history", [])
            current_step = session.get("current_step", len(history) - 1)
            
            # Truncate redo history
            history = history[:current_step + 1]
            history.append(file_dict)
            new_step = len(history) - 1
            
            ref.set({
                "file_history": history,
                "current_step": new_step
            })
            return new_step, len(history)
    except Exception as e:
        logger.error(f"Error pushing version for {user_id}: {e}")
    return 0, 1

def step_undo(user_id: int) -> Optional[Tuple[dict, int, int]]:
    """Steps backward in history."""
    try:
        if firebase_admin._apps:
            ref = db.reference(f"users/{user_id}/session")
            session = ref.get()
            if session and "file_history" in session:
                history = session["file_history"]
                current_step = session.get("current_step", 0)
                if current_step > 0:
                    new_step = current_step - 1
                    ref.update({"current_step": new_step})
                    return history[new_step], new_step, len(history)
    except Exception as e:
        logger.error(f"Error during undo for {user_id}: {e}")
    return None

def step_redo(user_id: int) -> Optional[Tuple[dict, int, int]]:
    """Steps forward in history."""
    try:
        if firebase_admin._apps:
            ref = db.reference(f"users/{user_id}/session")
            session = ref.get()
            if session and "file_history" in session:
                history = session["file_history"]
                current_step = session.get("current_step", 0)
                if current_step < len(history) - 1:
                    new_step = current_step + 1
                    ref.update({"current_step": new_step})
                    return history[new_step], new_step, len(history)
    except Exception as e:
        logger.error(f"Error during redo for {user_id}: {e}")
    return None

def clear_session(user_id: int):
    """Completely deletes user's session history."""
    try:
        if firebase_admin._apps:
            db.reference(f"users/{user_id}/session").delete()
    except Exception as e:
        logger.error(f"Error clearing session for {user_id}: {e}")

# --- USER CREDITS & HELPERS ---

def get_user_credits_and_refs(user_id: int):
    credits_val = 10
    referrals_val = 0
    try:
        if firebase_admin._apps:
            data = db.reference(f"users/{user_id}").get()
            if data and isinstance(data, dict):
                credits_val = data.get("credits", 10)
                referrals_val = data.get("referrals", 0)
    except Exception as e:
        logger.error(f"Error fetching user stats: {e}")
    return credits_val, referrals_val

def deduct_user_credit(user_id: int) -> bool:
    current_credits, _ = get_user_credits_and_refs(user_id)
    if current_credits < 1:
        return False
    new_credits = current_credits - 1
    try:
        if firebase_admin._apps:
            db.reference(f"users/{user_id}/credits").set(new_credits)
    except Exception as e:
        logger.error(f"Error deducting credit: {e}")
    return True

def add_user_credits(user_id: int, amount: int):
    current_credits, _ = get_user_credits_and_refs(user_id)
    new_credits = current_credits + amount
    try:
        if firebase_admin._apps:
            db.reference(f"users/{user_id}/credits").set(new_credits)
    except Exception as e:
        logger.error(f"Error adding credits: {e}")
    return new_credits

def reset_user_credits(user_id: int):
    new_credits = 10
    try:
        if firebase_admin._apps:
            db.reference(f"users/{user_id}/credits").set(new_credits)
    except Exception as e:
        logger.error(f"Error resetting credits: {e}")
    return new_credits

def reward_referrer(referrer_id: int):
    current_credits, current_refs = get_user_credits_and_refs(referrer_id)
    new_credits = current_credits + 5
    new_refs = current_refs + 1
    try:
        if firebase_admin._apps:
            db.reference(f"users/{referrer_id}").update({
                "credits": new_credits,
                "referrals": new_refs
            })
    except Exception as e:
        logger.error(f"Error updating referrer reward: {e}")

async def is_subscribed(client: Client, user_id: int):
    if not CHANNELS:
        return True
    for channel in CHANNELS:
        try:
            await client.get_chat_member(channel, user_id)
        except UserNotParticipant:
            return False
        except Exception:
            return False
    return True

async def is_banned(user_id: int):
    try:
        if not firebase_admin._apps:
            return False
        return db.reference(f"banned/{user_id}").get() is True
    except Exception as e:
        logger.error(f"Firebase is_banned Error: {e}")
        return False

def get_media_stats(path: str):
    if not path or not os.path.exists(path):
        return "N/A", "UNKNOWN", "0 KB"
    try:
        with Image.open(path) as img:
            w, h = img.size
            details = f"{w}x{h}"
            fmt = str(img.format).upper() if img.format else "IMAGE"
    except Exception:
        details = os.path.basename(path)
        fmt = path.split(".")[-1].upper() if "." in path else "FILE"
    
    size_bytes = os.path.getsize(path)
    size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1048576 else f"{size_bytes / 1048576:.2f} MB"
    return details, fmt, size_str

async def get_force_sub_markup():
    buttons = []
    for i, channel in enumerate(CHANNELS, 1):
        url = f"https://t.me/{channel.replace('@','')}" if "@" in channel else f"https://t.me/c/{channel.replace('-100','')}/1"
        buttons.append([InlineKeyboardButton(f"📢 Join Channel {i}", url=url)])
    buttons.append([InlineKeyboardButton("🔄 Check Subscription", callback_data="go_home")])
    return InlineKeyboardMarkup(buttons)

# --- UI LAYOUTS & KEYBOARDS ---

def get_welcome_layout(user_id: int, first_name: str) -> str:
    credits_val, referrals_val = get_user_credits_and_refs(user_id)
    active = get_current_active_file(user_id)
    
    photo_block = ""
    if active:
        photo_block = (
            "🖼️ <b>Your Photo:</b>\n"
            f"▫️ <b>Resolution/Name:</b> <code>{active.get('details')}</code>\n"
            f"▫️ <b>Format:</b> <code>{active.get('format')}</code>\n"
            f"▫️ <b>Size:</b> <code>{active.get('size')}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )

    return (
        f"✨ <b>Welcome to EditMedia Pro, {first_name}!</b> 👑\n\n"
        "I am your advanced, high-speed media processing assistant. I can seamlessly resize, compress, convert formats, and generate cloud links with zero quality loss!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👤 <b>Your Profile:</b>\n"
        f"▫️ <b>Account ID:</b> <code>{user_id}</code>\n"
        f"▫️ <b>Available Credits:</b> 🪙 <code>{credits_val}</code>\n"
        f"▫️ <b>Total Referrals:</b> 👥 <code>{referrals_val}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{photo_block}"
        "💡 <i>Note: 1 Action = 1 Credit | Invite friends to earn 🪙 5 Credits per referral!</i>\n\n"
        "👇 Select an option below to get started:"
    )

def get_main_buttons(user_id: int):
    has_photo = get_current_active_file(user_id) is not None
    btns = [
        [InlineKeyboardButton("🎨 Start Editing", callback_data="menu_edit_media")]
    ]
    if has_photo:
        btns.append([InlineKeyboardButton("🔄 Change Photo", callback_data="ask_photo")])
    btns.append([InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")])
    btns.append([
        InlineKeyboardButton("🎧 Support", callback_data="show_support"),
        InlineKeyboardButton("📜 Rules & Info", callback_data="show_rules")
    ])
    if user_id == ADMIN_ID:
        btns.append([InlineKeyboardButton("⚙️ Admin Dashboard", callback_data="admin_main")])
    return InlineKeyboardMarkup(btns)

def get_loaded_caption(details: str, fmt: str, size: str, step: int = 0, total_steps: int = 1) -> str:
    version_info = f" (v{step + 1}/{total_steps})" if total_steps > 1 else ""
    return (
        f"✨ <b>Media Successfully Loaded!</b> 🚀{version_info}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>Active File Details:</b>\n"
        f"▫️ <b>Resolution/Name:</b> <code>{details}</code>\n"
        f"▫️ <b>Format:</b> <code>{fmt}</code>\n"
        f"▫️ <b>Size:</b> <code>{size}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛠️ <b>Processing Workshop:</b>\n"
        "Choose an action below to instantly process your file."
    )

def get_workshop_buttons(current_step: int = 0, total_steps: int = 1):
    btns = []
    
    # Undo / Redo controls row
    history_row = []
    if current_step > 0:
        history_row.append(InlineKeyboardButton("↩️ Undo", callback_data="history_undo"))
    if current_step < total_steps - 1:
        history_row.append(InlineKeyboardButton("↪️ Redo", callback_data="history_redo"))
    if history_row:
        btns.append(history_row)
        
    btns.extend([
        [InlineKeyboardButton("📐 Resize", callback_data="op_resize"), InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
        [InlineKeyboardButton("✂️ Format Converter", callback_data="op_convert"), InlineKeyboardButton("📄 Image ➔ PDF", callback_data="op_pdf")],
        [InlineKeyboardButton("🔗 Generate Cloud Link", callback_data="op_link")],
        [InlineKeyboardButton("🎨 Edit Another File", callback_data="ask_photo"), InlineKeyboardButton("« Main Menu", callback_data="go_home")]
    ])
    return InlineKeyboardMarkup(btns)

async def safe_edit_caption_or_text(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None):
    try:
        if message.photo or message.document:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
        else:
            await message.edit_text(text=text, reply_markup=reply_markup)
    except errors.MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"safe_edit_caption_or_text error: {e}")

async def safe_edit(query: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None):
    try:
        if query.message.photo or query.message.document:
            await query.message.edit_caption(caption=text, reply_markup=reply_markup)
        else:
            await query.message.edit_text(text, reply_markup=reply_markup)
    except errors.MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"safe_edit error: {e}")

# --- WEB SERVER FOR RENDER HEALTH CHECKS ---
async def handle_health_check(request):
    return web.Response(text="Bot Alive", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

# --- BOT INITIALIZATION ---
bot = Client("EditMediaBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, parse_mode=ParseMode.HTML)

# --- COMMANDS & ROUTING ---

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id):
        return
    
    USER_STATES[user_id] = {"state": STATE_NONE}

    # Referral & Registration Logic
    try:
        if firebase_admin._apps:
            db_ref = db.reference(f"users/{user_id}")
            user_record = db_ref.get()
            if not user_record:
                referrer_id = None
                if len(message.command) > 1 and message.command[1].startswith("ref_"):
                    ref_code = message.command[1].replace("ref_", "").strip()
                    if ref_code.isdigit() and int(ref_code) != user_id:
                        referrer_id = int(ref_code)

                db_ref.set({
                    "name": message.from_user.first_name,
                    "username": message.from_user.username,
                    "credits": 10,
                    "referrals": 0,
                    "referred_by": referrer_id
                })

                if referrer_id:
                    reward_referrer(referrer_id)
                    try:
                        await client.send_message(
                            referrer_id,
                            f"🎉 <b>New Referral Joined!</b>\n\n"
                            f"👤 <b>User:</b> {message.from_user.first_name}\n"
                            "🪙 <b>Reward:</b> +5 Credits added to your balance!"
                        )
                    except Exception:
                        pass

                if ADMIN_ID:
                    try:
                        await client.send_message(ADMIN_ID, f"🆕 <b>New User:</b> {message.from_user.first_name} (<code>{user_id}</code>)")
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"Registration/Referral Error: {e}")

    if not await is_subscribed(client, user_id):
        return await message.reply_text(
            "❌ <b>Access Denied!</b>\nPlease join our update channels to use this bot.",
            reply_markup=await get_force_sub_markup()
        )

    await message.reply_text(get_welcome_layout(user_id, message.from_user.first_name), reply_markup=get_main_buttons(user_id))

@bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    try:
        await query.answer()
    except Exception:
        pass

    user_id = query.from_user.id
    if await is_banned(user_id):
        return await query.answer("You are banned from using this bot.", show_alert=True)
    
    data = query.data

    # Main Menu: Keep session in Firebase intact
    if data == "go_home":
        USER_STATES[user_id] = {"state": STATE_NONE}
        if query.message.photo or query.message.document:
            try:
                await query.message.delete()
            except Exception:
                pass
            return await client.send_message(user_id, get_welcome_layout(user_id, query.from_user.first_name), reply_markup=get_main_buttons(user_id))
        return await safe_edit(query, get_welcome_layout(user_id, query.from_user.first_name), get_main_buttons(user_id))

    # Directive 1: Start Editing restores from Firebase immediately
    if data == "menu_edit_media":
        session = get_session(user_id)
        if session and session.get("file_history"):
            history = session["file_history"]
            step = session.get("current_step", 0)
            active_file = history[step]
            caption = get_loaded_caption(
                active_file.get("details"),
                active_file.get("format"),
                active_file.get("size"),
                step,
                len(history)
            )
            buttons = get_workshop_buttons(step, len(history))
            try:
                await query.message.delete()
            except Exception:
                pass
            if active_file.get("is_doc", False):
                return await client.send_document(
                    chat_id=user_id,
                    document=active_file.get("file_id"),
                    caption=caption,
                    reply_markup=buttons,
                    force_document=True
                )
            else:
                return await client.send_photo(
                    chat_id=user_id,
                    photo=active_file.get("file_id"),
                    caption=caption,
                    reply_markup=buttons
                )
        else:
            # No active session, prompt upload
            USER_STATES[user_id] = {"state": STATE_WAITING_PHOTO, "prompt_msg_id": query.message.id}
            text = (
                "🎨 <b>Media & Document Workshop</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "<b>Welcome to the processing zone!</b>\n"
                "To get started, please send the image or document you wish to enhance. Our high-speed engine is ready to instantly resize, compress, convert, or generate cloud links for your file with zero quality loss.\n\n"
                "<b>Supported Uploads:</b>\n"
                "🖼️ Images: JPG, PNG, WEBP\n"
                "📄 Documents: PDF, DOCX, ZIP, etc.\n"
                "⚖️ Max Size: 20MB\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "⏳ <i>Waiting for your file...</i>"
            )
            return await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    # Edit Another File: Clears Firebase Session
    if data == "ask_photo":
        clear_session(user_id)
        USER_STATES[user_id] = {"state": STATE_WAITING_PHOTO, "prompt_msg_id": query.message.id}
        text = (
            "🎨 <b>Media & Document Workshop</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Ready for a new file!</b>\n"
            "Please send the new image or document you wish to process.\n\n"
            "<b>Supported Uploads:</b>\n"
            "🖼️ Images: JPG, PNG, WEBP\n"
            "📄 Documents: PDF, DOCX, ZIP, etc.\n"
            "⚖️ Max Size: 20MB\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⏳ <i>Waiting for your file...</i>"
        )
        if query.message.photo or query.message.document:
            try:
                await query.message.delete()
            except Exception:
                pass
            sent = await client.send_message(user_id, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))
            USER_STATES[user_id]["prompt_msg_id"] = sent.id
            return
        return await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    # Directive 2: Undo History Action
    if data == "history_undo":
        undo_res = step_undo(user_id)
        if undo_res:
            target_file, new_step, total_steps = undo_res
            caption = get_loaded_caption(
                target_file.get("details"),
                target_file.get("format"),
                target_file.get("size"),
                new_step,
                total_steps
            )
            buttons = get_workshop_buttons(new_step, total_steps)
            is_doc = target_file.get("is_doc", False) or target_file.get("format", "").lower() in ["pdf", "webp"]
            try:
                if is_doc:
                    media = InputMediaDocument(media=target_file["file_id"], caption=caption)
                else:
                    media = InputMediaPhoto(media=target_file["file_id"], caption=caption)
                await query.message.edit_message_media(media=media, reply_markup=buttons)
            except Exception:
                try:
                    await query.message.delete()
                except Exception:
                    pass
                if is_doc:
                    await client.send_document(user_id, target_file["file_id"], caption=caption, reply_markup=buttons, force_document=True)
                else:
                    await client.send_photo(user_id, target_file["file_id"], caption=caption, reply_markup=buttons)
            return await query.answer("↩️ Undone!")
        else:
            return await query.answer("No earlier steps to undo.", show_alert=True)

    # Directive 2: Redo History Action
    if data == "history_redo":
        redo_res = step_redo(user_id)
        if redo_res:
            target_file, new_step, total_steps = redo_res
            caption = get_loaded_caption(
                target_file.get("details"),
                target_file.get("format"),
                target_file.get("size"),
                new_step,
                total_steps
            )
            buttons = get_workshop_buttons(new_step, total_steps)
            is_doc = target_file.get("is_doc", False) or target_file.get("format", "").lower() in ["pdf", "webp"]
            try:
                if is_doc:
                    media = InputMediaDocument(media=target_file["file_id"], caption=caption)
                else:
                    media = InputMediaPhoto(media=target_file["file_id"], caption=caption)
                await query.message.edit_message_media(media=media, reply_markup=buttons)
            except Exception:
                try:
                    await query.message.delete()
                except Exception:
                    pass
                if is_doc:
                    await client.send_document(user_id, target_file["file_id"], caption=caption, reply_markup=buttons, force_document=True)
                else:
                    await client.send_photo(user_id, target_file["file_id"], caption=caption, reply_markup=buttons)
            return await query.answer("↪️ Redone!")
        else:
            return await query.answer("No steps to redo.", show_alert=True)

    # Back to Workshop from a tool menu
    if data == "menu_workshop_back":
        session = get_session(user_id)
        if not session or not session.get("file_history"):
            return await safe_edit(query, get_welcome_layout(user_id, query.from_user.first_name), get_main_buttons(user_id))
        history = session["file_history"]
        step = session.get("current_step", 0)
        active_file = history[step]
        caption = get_loaded_caption(
            active_file.get("details"),
            active_file.get("format"),
            active_file.get("size"),
            step,
            len(history)
        )
        return await safe_edit_caption_or_text(query.message, caption, reply_markup=get_workshop_buttons(step, len(history)))

    # Cancel ongoing async tasks
    if data == "cancel_active_task":
        task = USER_STATES.get(user_id, {}).get("active_task")
        if task and not task.done():
            task.cancel()
            await query.answer("❌ Task cancelled!", show_alert=False)
        else:
            await query.answer("No active task to cancel.", show_alert=False)
            active_file = get_current_active_file(user_id)
            if active_file:
                session = get_session(user_id) or {}
                step = session.get("current_step", 0)
                tot = len(session.get("file_history", [1]))
                caption = get_loaded_caption(active_file.get("details"), active_file.get("format"), active_file.get("size"), step, tot)
                await safe_edit_caption_or_text(query.message, caption, reply_markup=get_workshop_buttons(step, tot))
        return

    # Refer & Earn
    if data == "show_referral":
        credits_val, referrals_val = get_user_credits_and_refs(user_id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        text = (
            "🎁 <b>Refer & Earn Credits</b>\n\n"
            "Invite your friends to use EditMedia Pro and earn free credits!\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Your Referral Link:</b>\n<code>{ref_link}</code>\n\n"
            f"👥 <b>Your Referrals:</b> <code>{referrals_val}</code> Users\n"
            f"🪙 <b>Your Credits:</b> <code>{credits_val}</code> Credits\n"
            "▫️ <b>Reward:</b> 🪙 5 Credits per successful invite!\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Share your link with friends or channels to get unlimited credits!"
        )
        share_url = f"https://t.me/share/url?url={ref_link}&text=Edit%20your%20images%20with%20zero%20quality%20loss%20on%20EditMedia%20Pro!"
        btns = [
            [InlineKeyboardButton("🔗 Share Referral Link", url=share_url)],
            [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
        ]
        return await safe_edit(query, text, InlineKeyboardMarkup(btns))

    # Support Menu
    if data == "show_support":
        text = (
            "📞 sᴜᴘᴘᴏʀᴛ \n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ɪғ ʏᴏᴜ ʜᴀᴠᴇ ᴀɴʏ ᴘʀᴏʙʟᴇᴍs, ʏᴏᴜ ᴄᴀɴ ᴍᴇssᴀɢᴇ ᴍᴇ.\n\n"
            "👤 ᴀᴅᴍɪɴ: @DASFAIRSELLER01\n"
            "🤖 sᴜᴘᴘᴏʀᴛ: @DASASISSTANT_BOT\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ᴄᴏɴᴛɪɴᴜᴇ ᴡɪᴛʜ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ 👇"
        )
        return await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    # Rules & Info
    if data == "show_rules":
        text = (
            "📜 <b>Rules & Information</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣ <b>Max File Size:</b> Up to 20MB per file.\n"
            "2️⃣ <b>Sticker Prevention:</b> WEBP & PDF files are automatically handled as documents to prevent unwanted sticker conversions.\n"
            "3️⃣ <b>Credit Policy:</b> Each media transformation consumes 🪙 1 Credit. Earn 🪙 5 Credits for every friend who joins using your referral link.\n"
            "4️⃣ <b>Undo/Redo:</b> Every transformation is tracked in Firebase history. Navigate versions freely without losing progress!\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        return await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    # Admin Dashboard
    if data == "admin_main" and user_id == ADMIN_ID:
        USER_STATES[user_id] = {"state": STATE_NONE}
        count = "N/A"
        try:
            if firebase_admin._apps:
                users = db.reference("users").get()
                count = len(users) if users else 0
        except Exception as e:
            logger.error(f"Firebase Stats Error: {e}")
            count = "Offline"
        
        text = f"⚙️ <b>Admin Dashboard</b>\n\n📊 <b>Total Users:</b> <code>{count}</code>\n\nSelect an administration action below:"
        btns = [
            [InlineKeyboardButton("📣 Broadcast Message", callback_data="admin_bc")],
            [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"), InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")],
            [InlineKeyboardButton("➕ Add Credits", callback_data="admin_add_credits"), InlineKeyboardButton("🔄 Reset Credits", callback_data="admin_reset_credits")],
            [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
        ]
        return await safe_edit(query, text, InlineKeyboardMarkup(btns))

    if data in ["admin_bc", "admin_ban", "admin_unban", "admin_add_credits", "admin_reset_credits"] and user_id == ADMIN_ID:
        state_map = {
            "admin_bc": (STATE_ADMIN_BROADCAST, "💬 <b>Send the message you want to broadcast to all users.</b>"),
            "admin_ban": (STATE_ADMIN_BAN, "🚫 <b>Send the User ID you want to Ban.</b>"),
            "admin_unban": (STATE_ADMIN_UNBAN, "✅ <b>Send the User ID you want to Unban.</b>"),
            "admin_add_credits": (STATE_ADMIN_ADD_CREDIT, "➕ <b>Send User ID and Amount to add credits:</b>\nFormat: <code>user_id amount</code> (e.g., <code>123456789 20</code>)"),
            "admin_reset_credits": (STATE_ADMIN_RESET_CREDIT, "🔄 <b>Send User ID to reset credits back to 10:</b>\nFormat: <code>user_id</code> (e.g., <code>123456789</code>)")
        }
        chosen_state, prompt_text = state_map[data]
        USER_STATES[user_id] = {"state": chosen_state}
        return await safe_edit(query, prompt_text, InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="admin_main")]]))

    # Tools Navigation (Editing caption in place)
    active_file = get_current_active_file(user_id)
    if data.startswith("op_") and not active_file:
        USER_STATES[user_id] = {"state": STATE_WAITING_PHOTO}
        return await safe_edit(query, "🎨 <b>Please upload your file first to start editing.</b>", InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    if data == "op_resize":
        caption = (
            "📁 <b>Active File Details:</b>\n"
            f"▫️ <b>Resolution/Name:</b> <code>{active_file.get('details')}</code>\n"
            f"▫️ <b>Format:</b> <code>{active_file.get('format')}</code>\n"
            f"▫️ <b>Size:</b> <code>{active_file.get('size')}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📐 <b>Image Resizing Workshop:</b>\n"
            "Select a target resolution preset or choose custom dimensions:"
        )
        btns = [
            [InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
            [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
            [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
            [InlineKeyboardButton("4K (3840x2160)", callback_data="res_3840x2160")],
            [InlineKeyboardButton("⌨️ Custom Size", callback_data="res_custom")],
            [InlineKeyboardButton("« Back to Workshop", callback_data="menu_workshop_back")]
        ]
        return await safe_edit_caption_or_text(query.message, caption, reply_markup=InlineKeyboardMarkup(btns))

    elif data == "op_compress":
        caption = (
            "📁 <b>Active File Details:</b>\n"
            f"▫️ <b>Resolution/Name:</b> <code>{active_file.get('details')}</code>\n"
            f"▫️ <b>Format:</b> <code>{active_file.get('format')}</code>\n"
            f"▫️ <b>Size:</b> <code>{active_file.get('size')}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🗜️ <b>Image Compression Workshop:</b>\n"
            "Select your desired output quality level:"
        )
        btns = [
            [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
            [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
            [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
            [InlineKeyboardButton("« Back to Workshop", callback_data="menu_workshop_back")]
        ]
        return await safe_edit_caption_or_text(query.message, caption, reply_markup=InlineKeyboardMarkup(btns))

    elif data == "op_convert":
        caption = (
            "📁 <b>Active File Details:</b>\n"
            f"▫️ <b>Resolution/Name:</b> <code>{active_file.get('details')}</code>\n"
            f"▫️ <b>Format:</b> <code>{active_file.get('format')}</code>\n"
            f"▫️ <b>Size:</b> <code>{active_file.get('size')}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✂️ <b>Format Converter Workshop:</b>\n"
            "Select the new format you want to convert this file into:"
        )
        btns = [
            [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
            [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
            [InlineKeyboardButton("« Back to Workshop", callback_data="menu_workshop_back")]
        ]
        return await safe_edit_caption_or_text(query.message, caption, reply_markup=InlineKeyboardMarkup(btns))

    elif data == "op_pdf":
        await process_image_pdf(client, query.message, user_id)

    elif data == "op_link":
        await process_image_link(client, query.message, user_id)

    elif data.startswith("res_"):
        if data == "res_custom":
            USER_STATES[user_id] = {"state": STATE_WAITING_RESIZE_CUSTOM, "menu_msg_id": query.message.id}
            caption = (
                "📁 <b>Active File Details:</b>\n"
                f"▫️ <b>Resolution/Name:</b> <code>{active_file.get('details')}</code>\n"
                f"▫️ <b>Format:</b> <code>{active_file.get('format')}</code>\n"
                f"▫️ <b>Size:</b> <code>{active_file.get('size')}</code>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "⌨️ <b>Custom Resolution:</b>\n"
                "Please send the desired dimensions in <code>Width Height</code> format (e.g., <code>800 600</code>)."
            )
            await safe_edit_caption_or_text(query.message, caption, InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Workshop", callback_data="menu_workshop_back")]]))
        else:
            w, h = map(int, data.split("_")[1].split("x"))
            await process_image_resize(client, query.message, user_id, w, h)

    elif data.startswith("comp_"):
        await process_image_compress(client, query.message, user_id, int(data.split("_")[1]))

    elif data.startswith("conv_"):
        await process_image_convert(client, query.message, user_id, data.split("_")[1])

# --- CLEAN UPLOAD FLOW ---

@bot.on_message((filters.photo | filters.document) & filters.private)
async def media_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id):
        return
    
    # 1. Clean chat by deleting user's upload message
    try:
        await message.delete()
    except Exception:
        pass

    # 2. Delete bot's previous prompt if tracked
    prompt_id = USER_STATES.get(user_id, {}).get("prompt_msg_id")
    if prompt_id:
        try:
            await client.delete_messages(chat_id=user_id, message_ids=prompt_id)
        except Exception:
            pass

    is_doc = bool(message.document)
    file_id = message.document.file_id if is_doc else message.photo.file_id

    # 3. Download temporarily to extract precise stats
    temp_path = await message.download()
    details, fmt, size = get_media_stats(temp_path)
    
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception:
            pass

    # 4. Initialize session in Firebase (Step 0)
    initial_file = {
        "file_id": file_id,
        "details": details,
        "format": fmt,
        "size": size,
        "is_doc": is_doc
    }
    set_new_session(user_id, initial_file)
    USER_STATES[user_id] = {"state": STATE_NONE}

    # 5. Send single response with workshop buttons
    caption = get_loaded_caption(details, fmt, size, 0, 1)
    buttons = get_workshop_buttons(0, 1)

    force_doc = is_doc or fmt.lower() in ["webp", "pdf"]
    if force_doc:
        await client.send_document(
            chat_id=user_id,
            document=file_id,
            caption=caption,
            reply_markup=buttons,
            force_document=True
        )
    else:
        await client.send_photo(
            chat_id=user_id,
            photo=file_id,
            caption=caption,
            reply_markup=buttons
        )

# --- TEXT HANDLER & ADMIN PROCESSOR ---

@bot.on_message(filters.text & filters.private)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id):
        return

    if user_id not in USER_STATES:
        USER_STATES[user_id] = {"state": STATE_NONE}

    state = USER_STATES[user_id].get("state", STATE_NONE)

    if state == STATE_NONE:
        return

    # --- ADMIN PRIVILEGED ACTIONS ---
    if user_id == ADMIN_ID:
        if state == STATE_ADMIN_BROADCAST:
            status = None
            try:
                users = None
                try:
                    if firebase_admin._apps:
                        users = db.reference("users").get()
                except Exception as db_err:
                    logger.error(f"Database error during broadcast: {db_err}")
                    raise Exception(f"Database error ({db_err})")

                if not users:
                    raise Exception("No users found in database.")

                status = await message.reply_text("🚀 <b>Broadcasting message...</b>")
                success_count = 0
                failed_count = 0

                for uid in users:
                    try:
                        await message.copy(int(uid))
                        success_count += 1
                        await asyncio.sleep(0.05)  # Flood-wait delay
                    except Exception as err:
                        failed_count += 1
                        logger.warning(f"Broadcast failed for user {uid}: {err}")
                        continue

                await status.edit_text(
                    "✅ <b>Broadcast Completed!</b>\n\n"
                    f"🟢 <b>Sent:</b> <code>{success_count}</code>\n"
                    f"🔴 <b>Failed:</b> <code>{failed_count}</code>"
                )
            except Exception as e:
                logger.error(f"Broadcast Error: {e}")
                if status:
                    try:
                        await status.delete()
                    except Exception:
                        pass
                await message.reply_text(f"❌ <b>Broadcast Failed:</b> {e}")
            finally:
                USER_STATES[user_id]["state"] = STATE_NONE
            return

        elif state == STATE_ADMIN_BAN:
            try:
                target_id = message.text.strip()
                if firebase_admin._apps:
                    db.reference(f"banned/{target_id}").set(True)
                await message.reply_text(f"🚫 User <code>{target_id}</code> has been Banned.")
            except Exception as e:
                logger.error(f"Ban Error: {e}")
                await message.reply_text(f"❌ <b>Ban Failed:</b> {e}")
            finally:
                USER_STATES[user_id]["state"] = STATE_NONE
            return

        elif state == STATE_ADMIN_UNBAN:
            try:
                target_id = message.text.strip()
                if firebase_admin._apps:
                    db.reference(f"banned/{target_id}").delete()
                await message.reply_text(f"✅ User <code>{target_id}</code> has been Unbanned.")
            except Exception as e:
                logger.error(f"Unban Error: {e}")
                await message.reply_text(f"❌ <b>Unban Failed:</b> {e}")
            finally:
                USER_STATES[user_id]["state"] = STATE_NONE
            return

        elif state == STATE_ADMIN_ADD_CREDIT:
            try:
                parts = message.text.strip().split()
                if len(parts) != 2:
                    raise ValueError("Format: <code>user_id amount</code> (e.g. <code>123456789 25</code>)")
                target_id, amount = int(parts[0]), int(parts[1])
                new_bal = add_user_credits(target_id, amount)
                await message.reply_text(f"✅ Added <code>{amount}</code> Credits to <code>{target_id}</code>.\nNew Balance: 🪙 <code>{new_bal}</code>")
                try:
                    await client.send_message(target_id, f"🎁 <b>Credits Added!</b>\nAdmin added 🪙 <code>{amount}</code> Credits to your balance!\nCurrent Balance: 🪙 <code>{new_bal}</code>")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Add Credits Error: {e}")
                await message.reply_text(f"❌ <b>Failed to add credits:</b> {e}")
            finally:
                USER_STATES[user_id]["state"] = STATE_NONE
            return

        elif state == STATE_ADMIN_RESET_CREDIT:
            try:
                target_id = int(message.text.strip())
                new_bal = reset_user_credits(target_id)
                await message.reply_text(f"🔄 Credits for <code>{target_id}</code> reset to 🪙 <code>{new_bal}</code>.")
                try:
                    await client.send_message(target_id, f"ℹ️ Your credits have been reset to 🪙 <code>{new_bal}</code> by an Administrator.")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Reset Credits Error: {e}")
                await message.reply_text(f"❌ <b>Failed to reset credits:</b> {e}")
            finally:
                USER_STATES[user_id]["state"] = STATE_NONE
            return

    # --- USER CUSTOM RESIZE ---
    if state == STATE_WAITING_RESIZE_CUSTOM:
        try:
            try:
                await message.delete()
            except Exception:
                pass
            parts = message.text.strip().split()
            if len(parts) != 2:
                raise ValueError("Expected two dimensions")
            w, h = int(parts[0]), int(parts[1])
            if w <= 0 or h <= 0:
                raise ValueError("Dimensions must be positive")
            await process_image_resize(client, None, user_id, w, h)
        except ValueError:
            await message.reply_text("⚠️ <b>Invalid Format!</b> Please send valid numbers in 'Width Height' format (e.g., <code>1280 720</code>).")
        except Exception as e:
            logger.error(f"Resize Error: {e}")
            await message.reply_text(f"❌ <b>Error:</b> {e}")
        finally:
            USER_STATES[user_id]["state"] = STATE_NONE
        return

# --- CHAINED EDITING & PROCESSING ENGINES ---

async def send_chained_success_file(client: Client, user_id: int, file_path: str, action_title: str):
    """Sends new file, appends version to Firebase history, and renders Undo/Redo buttons."""
    deduct_user_credit(user_id)
    details, fmt, size = get_media_stats(file_path)
    is_doc = fmt.lower() in ["webp", "pdf"]
    
    # Push version to Firebase to get the new step and count
    temp_dict = {
        "file_id": "",  # Populated after Telegram sends
        "details": details,
        "format": fmt,
        "size": size,
        "is_doc": is_doc
    }
    
    # Calculate step indicators
    session = get_session(user_id) or {}
    cur_step = session.get("current_step", -1)
    tot_steps = len(session.get("file_history", []))
    new_step = cur_step + 1
    new_total = new_step + 1
    
    caption = (
        f"✅ <b>{action_title}</b> (v{new_step + 1})\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>Active File Details:</b>\n"
        f"▫️ <b>Resolution/Name:</b> <code>{details}</code>\n"
        f"▫️ <b>Format:</b> <code>{fmt}</code>\n"
        f"▫️ <b>Size:</b> <code>{size}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛠️ <b>Continue Chained Editing:</b>\n"
        "Choose an action below or use Undo/Redo."
    )
    
    buttons = get_workshop_buttons(new_step, new_total)
    
    if is_doc:
        caption += "\n\n💡 <b>Note:</b> Sent as a document to preserve format/quality."
        sent = await client.send_document(
            chat_id=user_id,
            document=file_path,
            caption=caption,
            reply_markup=buttons,
            force_document=True
        )
        new_file_id = sent.document.file_id
    else:
        sent = await client.send_photo(
            chat_id=user_id,
            photo=file_path,
            caption=caption,
            reply_markup=buttons
        )
        new_file_id = sent.photo.file_id

    # Commit full version record
    temp_dict["file_id"] = new_file_id
    push_new_version(user_id, temp_dict)

    # Local cleanup
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass

async def process_image_resize(client: Client, msg: Message, user_id: int, w: int, h: int):
    active_file = get_current_active_file(user_id)
    if not active_file:
        await client.send_message(user_id, "❌ <b>No active image found.</b>")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ <b>Insufficient Credits!</b>\n\n"
            "You need at least 🪙 1 Credit to process this media.\n"
            "Invite friends via <b>🎁 Refer & Earn</b> to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    local_input = await client.download_media(active_file["file_id"])
    timestamp = int(asyncio.get_event_loop().time())
    out = f"proc_{user_id}_{timestamp}.png"

    try:
        with Image.open(local_input) as img:
            img.resize((w, h), Image.Resampling.LANCZOS).save(out)
        
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        
        await send_chained_success_file(client, user_id, out, f"Resize Successful! 📐 ({w}x{h})")
    except Exception as e:
        logger.error(f"Resize Error: {e}")
        await client.send_message(user_id, f"❌ <b>Failed to resize image:</b> {e}")
    finally:
        for f in [local_input, out]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

async def process_image_compress(client: Client, msg: Message, user_id: int, qual: int):
    active_file = get_current_active_file(user_id)
    if not active_file:
        await client.send_message(user_id, "❌ <b>No active image found.</b>")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ <b>Insufficient Credits!</b>\n\n"
            "You need at least 🪙 1 Credit to process this media.\n"
            "Invite friends via <b>🎁 Refer & Earn</b> to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    local_input = await client.download_media(active_file["file_id"])
    timestamp = int(asyncio.get_event_loop().time())
    out = f"proc_{user_id}_{timestamp}.jpg"

    try:
        with Image.open(local_input) as img:
            img.convert("RGB").save(out, "JPEG", quality=qual, optimize=True)
            
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        
        await send_chained_success_file(client, user_id, out, f"Compression Successful! 🗜️ ({qual}%)")
    except Exception as e:
        logger.error(f"Compress Error: {e}")
        await client.send_message(user_id, f"❌ <b>Failed to compress image:</b> {e}")
    finally:
        for f in [local_input, out]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

async def process_image_convert(client: Client, msg: Message, user_id: int, fmt: str):
    active_file = get_current_active_file(user_id)
    if not active_file:
        await client.send_message(user_id, "❌ <b>No active image found.</b>")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ <b>Insufficient Credits!</b>\n\n"
            "You need at least 🪙 1 Credit to process this media.\n"
            "Invite friends via <b>🎁 Refer & Earn</b> to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    local_input = await client.download_media(active_file["file_id"])
    timestamp = int(asyncio.get_event_loop().time())
    out = f"proc_{user_id}_{timestamp}.{fmt.lower()}"

    try:
        with Image.open(local_input) as img:
            if fmt.lower() in ["jpg", "jpeg"]:
                img = img.convert("RGB")
            img.save(out)
            
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        
        await send_chained_success_file(client, user_id, out, f"Format Conversion to {fmt.upper()} Successful! ✂️")
    except Exception as e:
        logger.error(f"Convert Error: {e}")
        await client.send_message(user_id, f"❌ <b>Failed to convert image:</b> {e}")
    finally:
        for f in [local_input, out]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

async def process_image_pdf(client: Client, msg: Message, user_id: int):
    active_file = get_current_active_file(user_id)
    if not active_file:
        await client.send_message(user_id, "❌ <b>No active image found.</b>")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ <b>Insufficient Credits!</b>\n\n"
            "You need at least 🪙 1 Credit to process this media.\n"
            "Invite friends via <b>🎁 Refer & Earn</b> to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_active_task")]])
    status_text = (
        "⚙️ <b>Processing...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>Active File Details:</b>\n"
        f"▫️ <b>Resolution/Name:</b> <code>{active_file.get('details')}</code>\n"
        f"▫️ <b>Format:</b> <code>{active_file.get('format')}</code>\n"
        f"▫️ <b>Size:</b> <code>{active_file.get('size')}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ <i>Generating PDF document...</i>"
    )

    await safe_edit_caption_or_text(msg, status_text, reply_markup=cancel_markup)

    async def _pdf_task():
        local_input = await client.download_media(active_file["file_id"])
        timestamp = int(asyncio.get_event_loop().time())
        out = f"proc_{user_id}_{timestamp}.pdf"
        try:
            await asyncio.sleep(0.3)
            with Image.open(local_input) as img:
                img.convert("RGB").save(out, "PDF")
            
            if msg:
                try:
                    await msg.delete()
                except Exception:
                    pass
            
            await send_chained_success_file(client, user_id, out, "PDF Generation Successful! 📄")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"PDF Error: {e}")
            await client.send_message(user_id, f"❌ <b>Failed to generate PDF:</b> {e}")
        finally:
            for f in [local_input, out]:
                if f and os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass

    task = asyncio.create_task(_pdf_task())
    USER_STATES[user_id]["active_task"] = task
    try:
        await task
    except asyncio.CancelledError:
        session = get_session(user_id) or {}
        step = session.get("current_step", 0)
        tot = len(session.get("file_history", [1]))
        await safe_edit_caption_or_text(msg, get_loaded_caption(active_file.get("details"), active_file.get("format"), active_file.get("size"), step, tot), reply_markup=get_workshop_buttons(step, tot))
    finally:
        USER_STATES[user_id]["active_task"] = None

# Directive 3: Universal Link Generation (Catbox.moe for all files: PDF, WEBP, JPG, ZIP)
async def process_image_link(client: Client, msg: Message, user_id: int):
    active_file = get_current_active_file(user_id)
    if not active_file:
        await client.send_message(user_id, "❌ <b>No active image found. Please upload an image first.</b>")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ <b>Insufficient Credits!</b>\n\n"
            "You need at least 🪙 1 Credit to generate a cloud link.\n"
            "Invite friends via <b>🎁 Refer & Earn</b> to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_active_task")]])
    status_text = (
        "⚙️ <b>Processing...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>Active File Details:</b>\n"
        f"▫️ <b>Resolution/Name:</b> <code>{active_file.get('details')}</code>\n"
        f"▫️ <b>Format:</b> <code>{active_file.get('format')}</code>\n"
        f"▫️ <b>Size:</b> <code>{active_file.get('size')}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ <i>Downloading & uploading to Catbox storage...</i>"
    )

    await safe_edit_caption_or_text(msg, status_text, reply_markup=cancel_markup)

    async def _upload_task():
        # Universal download via Pyrogram
        local_path = await client.download_media(active_file["file_id"], in_memory=False)
        try:
            async with aiohttp.ClientSession() as sess:
                with open(local_path, "rb") as f:
                    form = aiohttp.FormData()
                    form.add_field("reqtype", "fileupload")
                    form.add_field("fileToUpload", f)
                    
                    async with sess.post("https://catbox.moe/user/api.php", data=form) as resp:
                        res_text = await resp.text()
                        
                        if resp.status == 200 and res_text.startswith("https://"):
                            url = res_text.strip()
                            deduct_user_credit(user_id)
                            caption = (
                                "✅ <b>Cloud Link Generated!</b> 🔗\n"
                                "━━━━━━━━━━━━━━━━━━━━\n"
                                "📁 <b>Active File Details:</b>\n"
                                f"▫️ <b>Resolution/Name:</b> <code>{active_file.get('details')}</code>\n"
                                f"▫️ <b>Format:</b> <code>{active_file.get('format')}</code>\n"
                                f"▫️ <b>Size:</b> <code>{active_file.get('size')}</code>\n"
                                "━━━━━━━━━━━━━━━━━━━━\n"
                                f"🔗 <b>Public Link:</b> <code>{url}</code>"
                            )
                            session = get_session(user_id) or {}
                            step = session.get("current_step", 0)
                            tot = len(session.get("file_history", [1]))
                            btns = [
                                [InlineKeyboardButton("🔗 Open Cloud Link", url=url)],
                                [InlineKeyboardButton("📐 Resize", callback_data="op_resize"), InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
                                [InlineKeyboardButton("✂️ Format Converter", callback_data="op_convert"), InlineKeyboardButton("📄 Image ➔ PDF", callback_data="op_pdf")],
                                [InlineKeyboardButton("🎨 Edit Another File", callback_data="ask_photo"), InlineKeyboardButton("« Main Menu", callback_data="go_home")]
                            ]
                            await safe_edit_caption_or_text(msg, caption, reply_markup=InlineKeyboardMarkup(btns))
                        else:
                            session = get_session(user_id) or {}
                            step = session.get("current_step", 0)
                            tot = len(session.get("file_history", [1]))
                            await safe_edit_caption_or_text(msg, f"❌ <b>Link Generation Failed:</b> {res_text[:50]}", reply_markup=get_workshop_buttons(step, tot))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Catbox Error: {e}")
            session = get_session(user_id) or {}
            step = session.get("current_step", 0)
            tot = len(session.get("file_history", [1]))
            await safe_edit_caption_or_text(msg, f"❌ <b>Server Connection Failed:</b> {str(e)}", reply_markup=get_workshop_buttons(step, tot))
        finally:
            if local_path and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass

    task = asyncio.create_task(_upload_task())
    USER_STATES[user_id]["active_task"] = task
    try:
        await task
    except asyncio.CancelledError:
        session = get_session(user_id) or {}
        step = session.get("current_step", 0)
        tot = len(session.get("file_history", [1]))
        await safe_edit_caption_or_text(msg, get_loaded_caption(active_file.get("details"), active_file.get("format"), active_file.get("size"), step, tot), reply_markup=get_workshop_buttons(step, tot))
    finally:
        USER_STATES[user_id]["active_task"] = None

# --- MAIN RUNNER ---
async def main():
    global BOT_USERNAME
    await start_web_server()
    await bot.start()
    
    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username or "EditMediaBot"
    except Exception:
        BOT_USERNAME = "EditMediaBot"
        
    logger.info(f"EditMedia Pro is Online as @{BOT_USERNAME}!")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()