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

from pyrogram import Client, filters, idle, errors
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import UserNotParticipant
from aiohttp import web
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
SUPPORT_CHAT = os.getenv("SUPPORT_CHAT", "Telegram")
CHANNELS = [ch.strip() for ch in os.getenv("CHANNELS", "").split(",") if ch.strip()]
PORT = int(os.getenv("PORT", 8080))

# State Constants
STATE_NONE = 0
STATE_WAITING_PHOTO = 1
STATE_WAITING_RESIZE_CUSTOM = 2
STATE_ADMIN_BROADCAST = 3
STATE_ADMIN_BAN = 4
STATE_ADMIN_UNBAN = 5

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

# --- HELPERS & UI GENERATORS ---

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

# Directive 2: Upgraded Pro Welcome Message Layout
def get_welcome_layout(user_id, first_name):
    source = USER_DATA.get(user_id, {}).get("source")
    text = f"✨ **Welcome to EditMedia Pro, {first_name}!** 👑\n\nYour ultimate, high-speed media processing assistant."
    if source and os.path.exists(source):
        info = get_file_info(source)
        text += f"\n\n━━━━━━━━━━━━━━━━━━\n✅ **Active Image Details:**\n{info}\n━━━━━━━━━━━━━━━━━━"
    else:
        text += "\n\n💡 _No active image loaded. Click 'Edit Media' or upload a photo to start!_"
    return text

# Directive 2: Main Menu Inline Buttons
def get_main_buttons(user_id):
    has_photo = USER_DATA.get(user_id, {}).get("source") is not None
    btns = [
        [InlineKeyboardButton("🛠️ Edit Media", callback_data="menu_edit_media")]
    ]
    if has_photo:
        btns.append([InlineKeyboardButton("🔄 Change Active Photo", callback_data="ask_photo")])
    btns.append([
        InlineKeyboardButton("🎧 Support", callback_data="show_support"),
        InlineKeyboardButton("📜 Rules & Info", callback_data="show_rules")
    ])
    if user_id == ADMIN_ID:
        btns.append([InlineKeyboardButton("⚙️ Admin Dashboard", callback_data="admin_main")])
    return InlineKeyboardMarkup(btns)

# Directive 2: Edit Media Sub-Menu Buttons
def get_edit_media_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📐 Resize", callback_data="op_resize"), InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
        [InlineKeyboardButton("✂️ Format Converter", callback_data="op_convert"), InlineKeyboardButton("📄 Image ➔ PDF", callback_data="op_pdf")],
        [InlineKeyboardButton("🔗 Generate Cloud Link", callback_data="op_link")],
        [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
    ])

async def safe_edit(query: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None):
    """Safely edits text menus, or sends a new menu if clicked from a media message."""
    try:
        if query.message.photo or query.message.document:
            await query.message.reply_text(text, reply_markup=reply_markup)
        else:
            await query.message.edit_text(text, reply_markup=reply_markup)
    except errors.MessageNotModified:
        pass

async def send_processed_file(client: Client, user_id: int, file_path: str, action_text: str):
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

# --- WEB SERVER ---
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

# --- HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id):
        return
    
    try:
        if firebase_admin._apps:
            db_ref = db.reference(f"users/{user_id}")
            if not db_ref.get():
                db_ref.set({"name": message.from_user.first_name, "username": message.from_user.username})
                if ADMIN_ID: 
                    try:
                        await client.send_message(ADMIN_ID, f"🆕 **New User:** {message.from_user.first_name} (`{user_id}`)")
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"Firebase Register Error (Non-Fatal): {e}")

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

    # Directive 2: Sub-Menu Workshop
    if data == "menu_edit_media":
        text = "🛠️ **Media Editing Workshop**\n\nSelect a powerful tool below to process your active image:"
        return await safe_edit(query, text, get_edit_media_buttons())

    # Support Menu
    if data == "show_support":
        text = (f"🎧 **Help & Support Desk**\n\n"
                f"Need assistance, found a bug, or have a suggestion?\n"
                f"Feel free to connect with our official support representative: @{SUPPORT_CHAT}\n\n"
                f"We are here to help you 24/7!")
        return await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    # Rules & Info Menu
    if data == "show_rules":
        text = ("📜 **Rules & Information**\n\n"
                "1️⃣ **Max File Size:** Up to 20MB per file.\n"
                "2️⃣ **Sticker Prevention:** WEBP & PDF files are automatically handled as documents to protect transparency and prevent unwanted sticker conversions.\n"
                "3️⃣ **Privacy Guarantee:** All media files are wiped immediately from the server upon processing completion.")
        return await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]]))

    # Smart Photo Replacement Confirmed
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
                [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
            ]
            await client.send_message(user_id, "📐 **Choose Resize Preset:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "compress":
            btns = [
                [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
                [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
                [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
                [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
            ]
            await client.send_message(user_id, "🗜️ **Choose Quality:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "convert":
            btns = [
                [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
                [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
                [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
            ]
            await client.send_message(user_id, "✂️ **Choose Format:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "pdf":
            await process_image_pdf(client, None, user_id)
        elif action == "link":
            await process_image_link(client, None, user_id)
        else:
            await client.send_message(user_id, get_welcome_layout(user_id, query.from_user.first_name), reply_markup=get_main_buttons(user_id))
        return

    # Keep Old Photo
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
        return await safe_edit(query, "📸 **Please upload your new Image.**", InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="go_home")]]))

    # Admin Dashboard
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
        
        text = f"⚙️ **Admin Dashboard**\n\n📊 Total Users: `{count}`\n\nSelect an action below:"
        btns = [
            [InlineKeyboardButton("📣 Broadcast Message", callback_data="admin_bc")],
            [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"), InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")],
            [InlineKeyboardButton("« Back to Main Menu", callback_data="go_home")]
        ]
        return await safe_edit(query, text, InlineKeyboardMarkup(btns))

    if data in ["admin_bc", "admin_ban", "admin_unban"] and user_id == ADMIN_ID:
        state_map = {"admin_bc": STATE_ADMIN_BROADCAST, "admin_ban": STATE_ADMIN_BAN, "admin_unban": STATE_ADMIN_UNBAN}
        USER_DATA[user_id]["state"] = state_map[data]
        return await safe_edit(query, "💬 **Waiting for your input...**", InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="admin_main")]]))

    # Operation Triggers
    if data.startswith("op_"):
        action = data.split("_")[1]
        if not USER_DATA.get(user_id, {}).get("source"):
            USER_DATA[user_id] = {"state": STATE_WAITING_PHOTO, "action": action}
            return await safe_edit(query, f"💎 **Mode: {action.upper()}**\n\nPlease upload the image to continue.", InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu_edit_media")]]))
        
        USER_DATA[user_id]["action"] = action
        if action == "resize":
            btns = [
                [InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
                [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
                [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
                [InlineKeyboardButton("4K (3840x2160)", callback_data="res_3840x2160")],
                [InlineKeyboardButton("⌨️ Custom Size", callback_data="res_custom")],
                [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
            ]
            await safe_edit(query, "📐 **Choose Resize Preset:**", InlineKeyboardMarkup(btns))
        elif action == "compress":
            btns = [
                [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
                [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
                [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
                [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
            ]
            await safe_edit(query, "🗜️ **Choose Quality:**", InlineKeyboardMarkup(btns))
        elif action == "convert":
            btns = [
                [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
                [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
                [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
            ]
            await safe_edit(query, "✂️ **Choose Format:**", InlineKeyboardMarkup(btns))
        elif action == "pdf":
            await process_image_pdf(client, query.message, user_id)
        elif action == "link":
            await process_image_link(client, query.message, user_id)

    elif data.startswith("res_"):
        if data == "res_custom":
            USER_DATA[user_id]["state"] = STATE_WAITING_RESIZE_CUSTOM
            await safe_edit(query, "⌨️ Type: `Width Height` (e.g. `800 600`)", InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="menu_edit_media")]]))
        else:
            w, h = map(int, data.split("_")[1].split("x"))
            await process_image_resize(client, query.message, user_id, w, h)

    elif data.startswith("comp_"):
        await process_image_compress(client, query.message, user_id, int(data.split("_")[1]))

    elif data.startswith("conv_"):
        await process_image_convert(client, query.message, user_id, data.split("_")[1])

@bot.on_message((filters.photo | filters.document) & filters.private)
async def media_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id):
        return
    
    is_doc = bool(message.document)
    old_src = USER_DATA.get(user_id, {}).get("source")
    
    # Prompt replacement if a photo is already loaded
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

    # First-time Upload
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
            [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
        ]
        await message.reply_text("📐 **Choose Resize Preset:**", reply_markup=InlineKeyboardMarkup(btns))
    elif action == "compress":
        btns = [
            [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
            [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
            [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
            [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
        ]
        await message.reply_text("🗜️ **Choose Quality:**", reply_markup=InlineKeyboardMarkup(btns))
    elif action == "convert":
        btns = [
            [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
            [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
            [InlineKeyboardButton("« Back to Workshop", callback_data="menu_edit_media")]
        ]
        await message.reply_text("✂️ **Choose Format:**", reply_markup=InlineKeyboardMarkup(btns))
    elif action == "pdf":
        await process_image_pdf(client, None, user_id)
    elif action == "link":
        await process_image_link(client, None, user_id)
    else:
        await message.reply_text(get_welcome_layout(user_id, message.from_user.first_name), reply_markup=get_main_buttons(user_id))

# Directive 3: State Management & Broadcast Crash Prevention
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
                users = db.reference("users").get()
                if not users:
                    raise Exception("No users found in database.")

                status = await message.reply_text("🚀 **Broadcasting message...**")
                success_count = 0
                failed_count = 0

                for uid in users:
                    try:
                        await message.copy(int(uid))
                        success_count += 1
                        await asyncio.sleep(0.05)  # Flood-wait safety delay
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
                db.reference(f"banned/{target_id}").delete()
                await message.reply_text(f"✅ User `{target_id}` has been Unbanned.")
            except Exception as e:
                logger.error(f"Unban Error: {e}")
                await message.reply_text(f"❌ Unban Failed: {e}")
            finally:
                USER_DATA[user_id]["state"] = STATE_NONE
            return

    # --- USER ACTIONS ---
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

# --- CORE IMAGE PROCESSING LOGIC ---

async def process_image_resize(client: Client, msg: Message, user_id: int, w: int, h: int):
    path = USER_DATA.get(user_id, {}).get("source")
    if not path or not os.path.exists(path):
        await client.send_message(user_id, "❌ No active image found.")
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

# Directive 1: Catbox.moe Cloud Link Upload Logic (Strictly Preserved)
async def process_image_link(client: Client, msg: Message, user_id: int):
    path = USER_DATA.get(user_id, {}).get("source")
    if not path or not os.path.exists(path):
        await client.send_message(user_id, "❌ No active image found. Please upload an image first.")
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
                        out_info = get_file_info(path)
                        caption = f"✅ **Public Link Generated!**\n\n{out_info}\n\n🔗 `{url}`"
                        
                        btns = [
                            [InlineKeyboardButton("🔗 Open Cloud Link", url=url)],
                            [InlineKeyboardButton("🛠️ Edit Media", callback_data="menu_edit_media"), InlineKeyboardButton("« Main Menu", callback_data="go_home")]
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

# --- MAIN RUNNER ---
async def main():
    await start_web_server()
    await bot.start()
    logger.info("EditMediaBot Elite Mode Online")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
