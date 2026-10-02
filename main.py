import asyncio
import os
import json
import logging
import base64
from typing import Dict, List

# --- CRITICAL: Python 3.14 Loop Fix ---
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# --------------------------------------

import aiohttp
from aiohttp import web
from pyrogram import Client, filters, idle, errors
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
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

USER_DATA: Dict[int, dict] = {}

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

# --- DATABASE & CREDIT SYSTEM HELPERS ---

def get_user_credits_and_refs(user_id: int):
    """Fetches user credit & referral counts with persistent memory/Firebase synchronization."""
    if user_id in USER_DATA and "credits" in USER_DATA[user_id] and "referrals" in USER_DATA[user_id]:
        return USER_DATA[user_id]["credits"], USER_DATA[user_id]["referrals"]
    
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

    USER_DATA[user_id] = USER_DATA.get(user_id, {})
    USER_DATA[user_id]["credits"] = credits_val
    USER_DATA[user_id]["referrals"] = referrals_val
    return credits_val, referrals_val

def deduct_user_credit(user_id: int) -> bool:
    """Deducts 1 credit upon successful processing."""
    current_credits, _ = get_user_credits_and_refs(user_id)
    if current_credits < 1:
        return False
    
    new_credits = current_credits - 1
    USER_DATA[user_id]["credits"] = new_credits
    try:
        if firebase_admin._apps:
            db.reference(f"users/{user_id}/credits").set(new_credits)
    except Exception as e:
        logger.error(f"Error deducting credit: {e}")
    return True

def add_user_credits(user_id: int, amount: int):
    """Adds specified credits to a user."""
    current_credits, _ = get_user_credits_and_refs(user_id)
    new_credits = current_credits + amount
    USER_DATA[user_id]["credits"] = new_credits
    try:
        if firebase_admin._apps:
            db.reference(f"users/{user_id}/credits").set(new_credits)
    except Exception as e:
        logger.error(f"Error adding credits: {e}")
    return new_credits

def reset_user_credits(user_id: int):
    """Resets user credits back to 10."""
    new_credits = 10
    USER_DATA[user_id]["credits"] = new_credits
    try:
        if firebase_admin._apps:
            db.reference(f"users/{user_id}/credits").set(new_credits)
    except Exception as e:
        logger.error(f"Error resetting credits: {e}")
    return new_credits

def reward_referrer(referrer_id: int):
    """Awards +5 credits and +1 referral count to the referrer."""
    current_credits, current_refs = get_user_credits_and_refs(referrer_id)
    new_credits = current_credits + 5
    new_refs = current_refs + 1
    USER_DATA[referrer_id]["credits"] = new_credits
    USER_DATA[referrer_id]["referrals"] = new_refs
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

def get_file_info(path):
    if not path or not os.path.exists(path):
        return "No active image."
    try:
        with Image.open(path) as img:
            w, h = img.size
            fmt = img.format
        size_bytes = os.path.getsize(path)
        size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1048576 else f"{size_bytes / 1048576:.2f} MB"
        return f"📏 **Resolution:** `{w}x{h}`\n📄 **Format:** `{fmt}`\n🗂️ **Size:** `{size_str}`"
    except Exception:
        return "Unable to read image info."

async def get_force_sub_markup():
    buttons = []
    for i, channel in enumerate(CHANNELS, 1):
        url = f"https://t.me/{channel.replace('@','')}" if "@" in channel else f"https://t.me/c/{channel.replace('-100','')}/1"
        buttons.append([InlineKeyboardButton(f"📢 Join Channel {i}", url=url)])
    buttons.append([InlineKeyboardButton("🔄 Check Subscription", callback_data="go_home")])
    return InlineKeyboardMarkup(buttons)

# --- UI LAYOUTS & MENUS ---

def get_welcome_layout(user_id: int, first_name: str) -> str:
    credits_val, referrals_val = get_user_credits_and_refs(user_id)
    source = USER_DATA.get(user_id, {}).get("source")
    
    photo_block = ""
    if source and os.path.exists(source):
        try:
            with Image.open(source) as img:
                w, h = img.size
                fmt = img.format
            size_bytes = os.path.getsize(source)
            size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1048576 else f"{size_bytes / 1048576:.2f} MB"
            photo_block = (
                "🖼️ Your Photo:\n"
                f"▫️ Resolution: `{w}x{h}`\n"
                f"▫️ Format: `{fmt}`\n"
                f"▫️ Size: `{size_str}`\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )
        except Exception:
            pass

    text = (
        f"✨ Welcome to EditMedia Pro, {first_name}! 👑\n\n"
        "I am your advanced, high-speed media processing assistant. I can seamlessly resize, compress, convert formats, and generate cloud links with zero quality loss!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👤 Your Profile:\n"
        f"▫️ Account ID: `{user_id}`\n"
        f"▫️ Available Credits: 🪙 `{credits_val}`\n"
        f"▫️ Total Referrals: 👥 `{referrals_val}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{photo_block}"
        "💡 _Note: 1 Action = 1 Credit | Invite friends to earn 🪙 5 Credits per referral!_\n\n"
        "👇 Select an option below to get started:"
    )
    return text

def get_main_buttons(user_id: int):
    has_photo = USER_DATA.get(user_id, {}).get("source") is not None
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

def get_edit_media_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📐 Resize", callback_data="op_resize"), InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
        [InlineKeyboardButton("✂️ Format Converter", callback_data="op_convert"), InlineKeyboardButton("📄 Image ➔ PDF", callback_data="op_pdf")],
        [InlineKeyboardButton("🔗 Generate Cloud Link", callback_data="op_link")],
        [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
    ])

async def safe_edit(query: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None):
    """Guarantees in-place editing of text menus without sending new spam messages."""
    try:
        if query.message.photo or query.message.document:
            await query.message.delete()
            await query.message.reply_text(text, reply_markup=reply_markup)
        else:
            await query.message.edit_text(text, reply_markup=reply_markup)
    except errors.MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"safe_edit error: {e}")
        try:
            await query.message.reply_text(text, reply_markup=reply_markup)
        except Exception:
            pass

async def send_processed_file(client: Client, user_id: int, file_path: str, action_text: str):
    deduct_user_credit(user_id)
    is_doc = USER_DATA.get(user_id, {}).get("is_doc", False)
    force_doc = is_doc or file_path.lower().endswith(".webp") or file_path.lower().endswith(".pdf")
    
    out_info = get_file_info(file_path)
    caption = f"✅ **{action_text}**\n\n{out_info}"
    
    if file_path.lower().endswith(".webp") or file_path.lower().endswith(".pdf"):
        caption += "\n\n💡 **Note:** Sent as a document to preserve format/quality."
        
    if force_doc:
        await client.send_document(
            chat_id=user_id,
            document=file_path,
            caption=caption,
            reply_markup=get_main_buttons(user_id),
            force_document=True
        )
    else:
        await client.send_photo(
            chat_id=user_id,
            photo=file_path,
            caption=caption,
            reply_markup=get_main_buttons(user_id)
        )

# --- WEB SERVER (RENDER COMPLIANCE) ---
async def handle_health_check(request):
    return web.Response(text="Bot Alive", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

# --- BOT INITIALIZATION ---
bot = Client("EditMediaBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- COMMANDS & ROUTING HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id):
        return
    
    source = USER_DATA.get(user_id, {}).get("source")
    is_doc = USER_DATA.get(user_id, {}).get("is_doc", False)
    USER_DATA[user_id] = {"state": STATE_NONE, "action": None}
    if source and os.path.exists(source):
        USER_DATA[user_id]["source"] = source
        USER_DATA[user_id]["is_doc"] = is_doc

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
                
                USER_DATA[user_id]["credits"] = 10
                USER_DATA[user_id]["referrals"] = 0

                if referrer_id:
                    reward_referrer(referrer_id)
                    try:
                        await client.send_message(
                            referrer_id,
                            f"🎉 **New Referral Joined!**\n\n"
                            f"👤 **User:** {message.from_user.first_name}\n"
                            f"🪙 **Reward:** +5 Credits added to your balance!"
                        )
                    except Exception:
                        pass

                if ADMIN_ID:
                    try:
                        await client.send_message(ADMIN_ID, f"🆕 **New User:** {message.from_user.first_name} (`{user_id}`)")
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"Registration/Referral Error: {e}")

    if not await is_subscribed(client, user_id):
        return await message.reply_text("❌ **Access Denied!**", reply_markup=await get_force_sub_markup())

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

    # Return to Main Menu
    if data == "go_home":
        USER_DATA[user_id] = USER_DATA.get(user_id, {})
        USER_DATA[user_id]["state"] = STATE_NONE
        USER_DATA[user_id]["action"] = None
        return await safe_edit(query, get_welcome_layout(user_id, query.from_user.first_name), get_main_buttons(user_id))

    # Editing Workshop Sub-Menu
    if data == "menu_edit_media":
        text = "🛠️ **Media Editing Workshop**\n\nSelect a powerful tool below to process your active image:"
        return await safe_edit(query, text, get_edit_media_buttons())

    # Refer & Earn Sub-Menu
    if data == "show_referral":
        credits_val, referrals_val = get_user_credits_and_refs(user_id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        text = (
            "🎁 **Refer & Earn Credits**\n\n"
            "Invite your friends to use EditMedia Pro and earn free credits!\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n"
            f"👥 **Your Referrals:** `{referrals_val}` Users\n"
            f"🪙 **Your Credits:** `{credits_val}` Credits\n"
            "▫️ **Reward:** 🪙 5 Credits per successful invite!\n"
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

    # Rules & Info Menu
    if data == "show_rules":
        text = (
            "📜 **Rules & Information**\n\n"
            "1️⃣ **Max File Size:** Up to 20MB per file.\n"
            "2️⃣ **Sticker Prevention:** WEBP & PDF files are automatically handled as documents to protect transparency and prevent unwanted sticker conversions.\n"
            "3️⃣ **Credit Policy:** Each media transformation consumes 🪙 1 Credit. Earn 🪙 5 Credits for every friend who joins using your referral link.\n"
            "4️⃣ **Privacy Guarantee:** All media files are wiped immediately from the server upon processing completion."
        )
        return await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    # Smart Photo Replacement Confirmation
    if data == "replace_photo":
        temp_path = USER_DATA.get(user_id, {}).get("temp_new_source")
        temp_is_doc = USER_DATA.get(user_id, {}).get("temp_is_doc", False)
        old_path = USER_DATA.get(user_id, {}).get("source")
        
        if old_path and os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass
        
        USER_DATA[user_id]["source"] = temp_path
        USER_DATA[user_id]["is_doc"] = temp_is_doc
        USER_DATA[user_id]["temp_new_source"] = None
        USER_DATA[user_id]["state"] = STATE_NONE
        
        await query.message.delete()
        
        action = USER_DATA.get(user_id, {}).get("action")
        USER_DATA[user_id]["action"] = None
        
        if action == "resize":
            btns = [
                [InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
                [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
                [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
                [InlineKeyboardButton("4K (3840x2160)", callback_data="res_3840x2160")],
                [InlineKeyboardButton("⌨️ Custom Size", callback_data="res_custom")],
                [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
            ]
            await client.send_message(user_id, "📐 **Choose Resize Preset:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "compress":
            btns = [
                [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
                [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
                [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
                [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
            ]
            await client.send_message(user_id, "🗜️ **Choose Quality:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "convert":
            btns = [
                [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
                [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
                [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
            ]
            await client.send_message(user_id, "✂️ **Choose Format:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "pdf":
            await process_image_pdf(client, None, user_id)
        elif action == "link":
            await process_image_link(client, None, user_id)
        else:
            await client.send_message(user_id, get_welcome_layout(user_id, query.from_user.first_name), reply_markup=get_main_buttons(user_id))
        return

    # Cancel Replacement
    if data == "keep_photo":
        temp_path = USER_DATA.get(user_id, {}).get("temp_new_source")
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        USER_DATA[user_id]["temp_new_source"] = None
        return await query.message.delete()

    # Change Photo Request
    if data == "ask_photo":
        USER_DATA[user_id]["state"] = STATE_WAITING_PHOTO
        return await safe_edit(query, "📸 **Please upload your new Image.**", InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    # Admin Dashboard Hub
    if data == "admin_main" and user_id == ADMIN_ID:
        USER_DATA[user_id]["state"] = STATE_NONE
        count = "N/A"
        try:
            if firebase_admin._apps:
                users = db.reference("users").get()
                count = len(users) if users else 0
        except Exception as e:
            logger.error(f"Firebase Stats Error: {e}")
            count = "Offline"
        
        text = f"⚙️ **Admin Dashboard**\n\n📊 Total Users: `{count}`\n\nSelect an administration action below:"
        btns = [
            [InlineKeyboardButton("📣 Broadcast Message", callback_data="admin_bc")],
            [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"), InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")],
            [InlineKeyboardButton("➕ Add Credits", callback_data="admin_add_credits"), InlineKeyboardButton("🔄 Reset Credits", callback_data="admin_reset_credits")],
            [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
        ]
        return await safe_edit(query, text, InlineKeyboardMarkup(btns))

    if data in ["admin_bc", "admin_ban", "admin_unban", "admin_add_credits", "admin_reset_credits"] and user_id == ADMIN_ID:
        state_map = {
            "admin_bc": (STATE_ADMIN_BROADCAST, "💬 **Send the message you want to broadcast to all users.**"),
            "admin_ban": (STATE_ADMIN_BAN, "🚫 **Send the User ID you want to Ban.**"),
            "admin_unban": (STATE_ADMIN_UNBAN, "✅ **Send the User ID you want to Unban.**"),
            "admin_add_credits": (STATE_ADMIN_ADD_CREDIT, "➕ **Send User ID and Amount to add credits:**\nFormat: `user_id amount` (e.g., `123456789 20`)"),
            "admin_reset_credits": (STATE_ADMIN_RESET_CREDIT, "🔄 **Send User ID to reset credits back to 10:**\nFormat: `user_id` (e.g., `123456789`)")
        }
        chosen_state, prompt_text = state_map[data]
        USER_DATA[user_id]["state"] = chosen_state
        return await safe_edit(query, prompt_text, InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="admin_main")]]))

    # Operation Triggers
    if data.startswith("op_"):
        action = data.split("_")[1]
        if not USER_DATA.get(user_id, {}).get("source"):
            USER_DATA[user_id] = {"state": STATE_WAITING_PHOTO, "action": action}
            return await safe_edit(query, f"💎 **Mode: {action.upper()}**\n\nPlease upload the image to continue.", InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))
        
        USER_DATA[user_id]["action"] = action
        if action == "resize":
            btns = [
                [InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
                [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
                [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
                [InlineKeyboardButton("4K (3840x2160)", callback_data="res_3840x2160")],
                [InlineKeyboardButton("⌨️ Custom Size", callback_data="res_custom")],
                [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
            ]
            await safe_edit(query, "📐 **Choose Resize Preset:**", InlineKeyboardMarkup(btns))
        elif action == "compress":
            btns = [
                [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
                [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
                [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
                [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
            ]
            await safe_edit(query, "🗜️ **Choose Quality:**", InlineKeyboardMarkup(btns))
        elif action == "convert":
            btns = [
                [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
                [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
                [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
            ]
            await safe_edit(query, "✂️ **Choose Format:**", InlineKeyboardMarkup(btns))
        elif action == "pdf":
            await process_image_pdf(client, query.message, user_id)
        elif action == "link":
            await process_image_link(client, query.message, user_id)

    elif data.startswith("res_"):
        if data == "res_custom":
            USER_DATA[user_id]["state"] = STATE_WAITING_RESIZE_CUSTOM
            await safe_edit(query, "⌨️ Type: `Width Height` (e.g. `800 600`)", InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="go_home")]]))
        else:
            w, h = map(int, data.split("_")[1].split("x"))
            await process_image_resize(client, query.message, user_id, w, h)

    elif data.startswith("comp_"):
        await process_image_compress(client, query.message, user_id, int(data.split("_")[1]))

    elif data.startswith("conv_"):
        await process_image_convert(client, query.message, user_id, data.split("_")[1])

# --- MEDIA HANDLER ---

@bot.on_message((filters.photo | filters.document) & filters.private)
async def media_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id):
        return
    
    is_doc = bool(message.document)
    old_src = USER_DATA.get(user_id, {}).get("source")
    
    # Prompt replacement if an image is already active
    if old_src and os.path.exists(old_src):
        status = await message.reply_text("⏳ **Downloading new image...**")
        path = await message.download()
        try:
            await status.delete()
        except Exception:
            pass
        
        USER_DATA[user_id] = USER_DATA.get(user_id, {})
        USER_DATA[user_id]["temp_new_source"] = path
        USER_DATA[user_id]["temp_is_doc"] = is_doc
        
        btns = [
            [InlineKeyboardButton("✅ Yes, Replace", callback_data="replace_photo")],
            [InlineKeyboardButton("❌ No, Keep Old", callback_data="keep_photo")]
        ]
        await message.reply_text("📸 **New Image Detected!** Do you want to replace your current active photo?", reply_markup=InlineKeyboardMarkup(btns))
        return

    # First-Time Image Upload
    status = await message.reply_text("⏳ **Downloading Image...**")
    path = await message.download()
    try:
        await status.delete()
    except Exception:
        pass
    
    USER_DATA[user_id] = USER_DATA.get(user_id, {})
    USER_DATA[user_id].update({"source": path, "state": STATE_NONE, "is_doc": is_doc})
    
    action = USER_DATA[user_id].get("action")
    USER_DATA[user_id]["action"] = None
    
    if action == "resize":
        btns = [
            [InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
            [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
            [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
            [InlineKeyboardButton("4K (3840x2160)", callback_data="res_3840x2160")],
            [InlineKeyboardButton("⌨️ Custom Size", callback_data="res_custom")],
            [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
        ]
        await message.reply_text("📐 **Choose Resize Preset:**", reply_markup=InlineKeyboardMarkup(btns))
    elif action == "compress":
        btns = [
            [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
            [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
            [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
            [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
        ]
        await message.reply_text("🗜️ **Choose Quality:**", reply_markup=InlineKeyboardMarkup(btns))
    elif action == "convert":
        btns = [
            [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
            [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
            [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
        ]
        await message.reply_text("✂️ **Choose Format:**", reply_markup=InlineKeyboardMarkup(btns))
    elif action == "pdf":
        await process_image_pdf(client, None, user_id)
    elif action == "link":
        await process_image_link(client, None, user_id)
    else:
        await message.reply_text(get_welcome_layout(user_id, message.from_user.first_name), reply_markup=get_main_buttons(user_id))

# --- TEXT HANDLER & ADMIN PROCESSOR ---

@bot.on_message(filters.text & filters.private)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id):
        return

    if user_id not in USER_DATA:
        USER_DATA[user_id] = {"state": STATE_NONE}

    state = USER_DATA[user_id].get("state", STATE_NONE)

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

                status = await message.reply_text("🚀 **Broadcasting message...**")
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
                    f"✅ **Broadcast Completed!**\n\n"
                    f"🟢 Sent: `{success_count}`\n"
                    f"🔴 Failed: `{failed_count}`"
                )
            except Exception as e:
                logger.error(f"Broadcast Error: {e}")
                if status:
                    try:
                        await status.delete()
                    except Exception:
                        pass
                await message.reply_text(f"❌ Broadcast Failed: {e}")
            finally:
                USER_DATA[user_id]["state"] = STATE_NONE
            return

        elif state == STATE_ADMIN_BAN:
            try:
                target_id = message.text.strip()
                if firebase_admin._apps:
                    db.reference(f"banned/{target_id}").set(True)
                await message.reply_text(f"🚫 User `{target_id}` has been Banned.")
            except Exception as e:
                logger.error(f"Ban Error: {e}")
                await message.reply_text(f"❌ Ban Failed: {e}")
            finally:
                USER_DATA[user_id]["state"] = STATE_NONE
            return

        elif state == STATE_ADMIN_UNBAN:
            try:
                target_id = message.text.strip()
                if firebase_admin._apps:
                    db.reference(f"banned/{target_id}").delete()
                await message.reply_text(f"✅ User `{target_id}` has been Unbanned.")
            except Exception as e:
                logger.error(f"Unban Error: {e}")
                await message.reply_text(f"❌ Unban Failed: {e}")
            finally:
                USER_DATA[user_id]["state"] = STATE_NONE
            return

        elif state == STATE_ADMIN_ADD_CREDIT:
            try:
                parts = message.text.strip().split()
                if len(parts) != 2:
                    raise ValueError("Format: `user_id amount` (e.g. `123456789 25`)")
                target_id, amount = int(parts[0]), int(parts[1])
                new_bal = add_user_credits(target_id, amount)
                await message.reply_text(f"✅ Added `{amount}` Credits to `{target_id}`.\nNew Balance: 🪙 `{new_bal}`")
                try:
                    await client.send_message(target_id, f"🎁 **Credits Added!**\nAdmin added 🪙 `{amount}` Credits to your balance!\nCurrent Balance: 🪙 `{new_bal}`")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Add Credits Error: {e}")
                await message.reply_text(f"❌ Failed to add credits: {e}")
            finally:
                USER_DATA[user_id]["state"] = STATE_NONE
            return

        elif state == STATE_ADMIN_RESET_CREDIT:
            try:
                target_id = int(message.text.strip())
                new_bal = reset_user_credits(target_id)
                await message.reply_text(f"🔄 Credits for `{target_id}` reset to 🪙 `{new_bal}`.")
                try:
                    await client.send_message(target_id, f"ℹ️ Your credits have been reset to 🪙 `{new_bal}` by an Administrator.")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Reset Credits Error: {e}")
                await message.reply_text(f"❌ Failed to reset credits: {e}")
            finally:
                USER_DATA[user_id]["state"] = STATE_NONE
            return

    # --- USER CUSTOM RESIZE ---
    if state == STATE_WAITING_RESIZE_CUSTOM:
        try:
            parts = message.text.strip().split()
            if len(parts) != 2:
                raise ValueError("Expected two dimensions")
            w, h = int(parts[0]), int(parts[1])
            if w <= 0 or h <= 0:
                raise ValueError("Dimensions must be positive")
            await process_image_resize(client, None, user_id, w, h)
        except ValueError:
            await message.reply_text("⚠️ **Invalid Format!** Please send valid numbers in 'Width Height' format (e.g., `1280 720`).")
        except Exception as e:
            logger.error(f"Resize Error: {e}")
            await message.reply_text(f"❌ Error: {e}")
        finally:
            USER_DATA[user_id]["state"] = STATE_NONE
        return

# --- IMAGE PROCESSING ENGINES ---

async def process_image_resize(client: Client, msg: Message, user_id: int, w: int, h: int):
    path = USER_DATA.get(user_id, {}).get("source")
    if not path or not os.path.exists(path):
        await client.send_message(user_id, "❌ No active image found.")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ **Insufficient Credits!**\n\n"
            "You need at least 🪙 1 Credit to process this media.\n"
            "Invite friends via **🎁 Refer & Earn** to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    out = f"res_{user_id}.png"
    status = None
    if msg:
        try:
            await msg.edit_text("⚙️ **Processing Resize...**")
        except Exception:
            status = await client.send_message(user_id, "⚙️ **Processing Resize...**")
    else:
        status = await client.send_message(user_id, "⚙️ **Processing Resize...**")

    try:
        with Image.open(path) as img:
            img.resize((w, h), Image.Resampling.LANCZOS).save(out)
        
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        if status:
            try:
                await status.delete()
            except Exception:
                pass
            
        await send_processed_file(client, user_id, out, f"Resized to {w}x{h}")
    except Exception as e:
        logger.error(f"Resize Error: {e}")
        await client.send_message(user_id, f"❌ Failed to resize image: {e}")
    finally:
        if os.path.exists(out):
            os.remove(out)

async def process_image_compress(client: Client, msg: Message, user_id: int, qual: int):
    path = USER_DATA.get(user_id, {}).get("source")
    if not path or not os.path.exists(path):
        await client.send_message(user_id, "❌ No active image found.")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ **Insufficient Credits!**\n\n"
            "You need at least 🪙 1 Credit to process this media.\n"
            "Invite friends via **🎁 Refer & Earn** to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    out = f"comp_{user_id}.jpg"
    status = None
    if msg:
        try:
            await msg.edit_text("⚙️ **Compressing Image...**")
        except Exception:
            status = await client.send_message(user_id, "⚙️ **Compressing Image...**")
    else:
        status = await client.send_message(user_id, "⚙️ **Compressing Image...**")

    try:
        with Image.open(path) as img:
            img.convert("RGB").save(out, "JPEG", quality=qual, optimize=True)
            
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        if status:
            try:
                await status.delete()
            except Exception:
                pass
            
        await send_processed_file(client, user_id, out, f"Compressed (Quality: {qual}%)")
    except Exception as e:
        logger.error(f"Compress Error: {e}")
        await client.send_message(user_id, f"❌ Failed to compress image: {e}")
    finally:
        if os.path.exists(out):
            os.remove(out)

async def process_image_convert(client: Client, msg: Message, user_id: int, fmt: str):
    path = USER_DATA.get(user_id, {}).get("source")
    if not path or not os.path.exists(path):
        await client.send_message(user_id, "❌ No active image found.")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ **Insufficient Credits!**\n\n"
            "You need at least 🪙 1 Credit to process this media.\n"
            "Invite friends via **🎁 Refer & Earn** to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    out = f"conv_{user_id}.{fmt}"
    status = None
    if msg:
        try:
            await msg.edit_text(f"⚙️ **Converting to {fmt.upper()}...**")
        except Exception:
            status = await client.send_message(user_id, f"⚙️ **Converting to {fmt.upper()}...**")
    else:
        status = await client.send_message(user_id, f"⚙️ **Converting to {fmt.upper()}...**")

    try:
        with Image.open(path) as img:
            if fmt in ["jpg", "jpeg"]:
                img = img.convert("RGB")
            img.save(out)
            
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        if status:
            try:
                await status.delete()
            except Exception:
                pass
            
        await send_processed_file(client, user_id, out, f"Format: {fmt.upper()}")
    except Exception as e:
        logger.error(f"Convert Error: {e}")
        await client.send_message(user_id, f"❌ Failed to convert image: {e}")
    finally:
        if os.path.exists(out):
            os.remove(out)

async def process_image_pdf(client: Client, msg: Message, user_id: int):
    path = USER_DATA.get(user_id, {}).get("source")
    if not path or not os.path.exists(path):
        await client.send_message(user_id, "❌ No active image found.")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ **Insufficient Credits!**\n\n"
            "You need at least 🪙 1 Credit to process this media.\n"
            "Invite friends via **🎁 Refer & Earn** to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    out = f"doc_{user_id}.pdf"
    status = None
    if msg:
        try:
            await msg.edit_text("⚙️ **Creating PDF...**")
        except Exception:
            status = await client.send_message(user_id, "⚙️ **Creating PDF...**")
    else:
        status = await client.send_message(user_id, "⚙️ **Creating PDF...**")

    try:
        with Image.open(path) as img:
            img.convert("RGB").save(out, "PDF")
            
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        if status:
            try:
                await status.delete()
            except Exception:
                pass
            
        await send_processed_file(client, user_id, out, "PDF Generated")
    except Exception as e:
        logger.error(f"PDF Error: {e}")
        await client.send_message(user_id, f"❌ Failed to generate PDF: {e}")
    finally:
        if os.path.exists(out):
            os.remove(out)

# Catbox.moe Cloud Link Upload Logic (Direct file stream upload)
async def process_image_link(client: Client, msg: Message, user_id: int):
    import aiohttp
    
    path = USER_DATA.get(user_id, {}).get("source")
    if not path or not os.path.exists(path):
        await client.send_message(user_id, "❌ No active image found. Please upload an image first.")
        return

    credits_val, _ = get_user_credits_and_refs(user_id)
    if credits_val < 1:
        await client.send_message(
            user_id,
            "⚠️ **Insufficient Credits!**\n\n"
            "You need at least 🪙 1 Credit to generate a cloud link.\n"
            "Invite friends via **🎁 Refer & Earn** to earn 🪙 5 Credits per invite!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_referral")]])
        )
        return

    if msg:
        try:
            await msg.delete()
        except Exception:
            pass

    status = await client.send_message(user_id, "📤 **Generating Public Link...**")
    
    try:
        async with aiohttp.ClientSession() as sess:
            with open(path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("reqtype", "fileupload")
                form.add_field("fileToUpload", f)
                
                async with sess.post("https://catbox.moe/user/api.php", data=form) as resp:
                    res_text = await resp.text()
                    
                    if resp.status == 200 and res_text.startswith("https://"):
                        url = res_text.strip()
                        deduct_user_credit(user_id)
                        out_info = get_file_info(path)
                        caption = f"✅ **Public Link Generated!**\n\n{out_info}\n\n🔗 `{url}`"
                        
                        btns = [
                            [InlineKeyboardButton("🔗 Open Cloud Link", url=url)],
                            [InlineKeyboardButton("🎨 Start Editing", callback_data="menu_edit_media"), InlineKeyboardButton("« Main Menu", callback_data="go_home")]
                        ]
                        await client.send_message(user_id, caption, reply_markup=InlineKeyboardMarkup(btns))
                    else:
                        await client.send_message(user_id, f"❌ Link Generation Failed: {res_text[:50]}")
    except Exception as e:
        logger.error(f"Catbox Error: {e}")
        await client.send_message(user_id, f"❌ Server Connection Failed. (Error: {str(e)})")
    finally: 
        try:
            await status.delete()
        except Exception:
            pass

# --- MAIN EXECUTOR ---
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
