import asyncio
import os
import json
import logging
import shutil
import aiohttp
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
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")
CHANNELS = os.getenv("CHANNELS", "").replace(" ", "").split(",")
PORT = int(os.getenv("PORT", 8080))

# State Constants
STATE_NONE = 0
STATE_WAITING_PHOTO = 1
STATE_WAITING_RESIZE_CUSTOM = 2
STATE_ADMIN_BROADCAST = 3

# Global Storage
USER_DATA: Dict[int, dict] = {}

# --- FIREBASE SETUP ---
try:
    if FIREBASE_JSON:
        cert_dict = json.loads(FIREBASE_JSON)
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred, {
            'databaseURL': cert_dict.get('databaseURL', f"https://{cert_dict['project_id']}-default-rtdb.firebaseio.com/")
        })
        logger.info("Firebase successfully initialized.")
except Exception as e:
    logger.error(f"Firebase Init Error: {e}")

# --- HELPERS ---

async def is_subscribed(client: Client, user_id: int):
    if not CHANNELS or not CHANNELS[0]: return True
    for channel in CHANNELS:
        try:
            await client.get_chat_member(channel, user_id)
        except UserNotParticipant: return False
        except Exception: return False
    return True

async def is_banned(user_id: int):
    try:
        return db.reference(f"banned/{user_id}").get() is True
    except: return False

def get_file_info(path):
    """Requirement 2: Extract Image Stats"""
    if not path or not os.path.exists(path): return "No active image."
    try:
        with Image.open(path) as img:
            w, h = img.size
            fmt = img.format
        size_bytes = os.path.getsize(path)
        size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1048576 else f"{size_bytes / 1048576:.2f} MB"
        return f"📏 **Resolution:** {w}x{h}\n📄 **Format:** {fmt}\n🗂️ **File Size:** {size_str}"
    except: return "Unable to read image info."

async def get_force_sub_markup():
    buttons = []
    for i, channel in enumerate(CHANNELS, 1):
        url = f"https://t.me/{channel.replace('@','')}" if "@" in channel else f"https://t.me/c/{channel.replace('-100','')}/1"
        buttons.append([InlineKeyboardButton(f"📢 Join Channel {i}", url=url)])
    buttons.append([InlineKeyboardButton("🔄 Check Subscription", callback_data="go_home")])
    return InlineKeyboardMarkup(buttons)

def update_user_stats(user_id, name, username=None):
    if not firebase_admin._apps: return False
    try:
        ref = db.reference(f"users/{user_id}")
        data = ref.get()
        is_new = data is None
        ref.update({"name": name, "username": username, "count": (data.get("count", 0) if data else 0) + 1})
        return is_new
    except Exception: return False

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

# --- KEYBOARDS ---

def get_main_markup(user_id):
    """Requirement 1 & 4: Navigation with persistent session"""
    has_photo = USER_DATA.get(user_id, {}).get("source") is not None
    buttons = [
        [InlineKeyboardButton("📐 Resize", callback_data="op_resize"), InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
        [InlineKeyboardButton("🔗 Public Link", callback_data="op_link")],
        [InlineKeyboardButton("📄 Image to PDF", callback_data="op_pdf"), InlineKeyboardButton("✂️ Converter", callback_data="op_convert")]
    ]
    if has_photo:
        buttons.append([InlineKeyboardButton("🔄 Change Photo", callback_data="ask_photo")])
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_main")])
    return InlineKeyboardMarkup(buttons)

def back_home():
    return [InlineKeyboardButton("« Back to Menu", callback_data="go_home")]

# --- HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if await is_banned(user_id): return
    
    is_new = update_user_stats(user_id, message.from_user.first_name, message.from_user.username)
    if is_new and ADMIN_ID:
        await client.send_message(ADMIN_ID, f"🆕 **New User:** {message.from_user.first_name} (`{user_id}`)")

    if not await is_subscribed(client, user_id):
        return await message.reply_text("❌ **Join Channels to Continue!**", reply_markup=await get_force_sub_markup())

    # Requirement 5: Identity Fix
    text = (f"✨ **Hello {message.from_user.first_name}!**\n\n"
            "Welcome to **EditMediaBot Premium**. I can process your images without quality loss.\n\n"
            "👇 Select an option to begin:")
    await message.reply_text(text, reply_markup=get_main_markup(user_id))

@bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    if await is_banned(user_id): return await query.answer("You are banned.", show_alert=True)
    
    data = query.data

    # Requirement 4: Message Navigation Fix
    if data == "go_home":
        USER_DATA[user_id] = USER_DATA.get(user_id, {"state": STATE_NONE})
        USER_DATA[user_id]["state"] = STATE_NONE
        img_info = get_file_info(USER_DATA[user_id].get("source"))
        text = f"✨ **Main Menu**\n\n{img_info}\n\nWhat would you like to do?"
        return await query.message.edit_text(text, reply_markup=get_main_markup(user_id))

    if data == "ask_photo":
        USER_DATA[user_id]["state"] = STATE_WAITING_PHOTO
        return await query.message.edit_text("📸 **Please send the new Image.**", reply_markup=InlineKeyboardMarkup([back_home()]))

    # Admin Panel (Requirement 3)
    if data == "admin_main" and user_id == ADMIN_ID:
        try:
            users = db.reference("users").get()
            count = len(users) if users else 0
        except: count = "Error fetching"
        
        adm_btns = [
            [InlineKeyboardButton("📣 Broadcast", callback_data="admin_bc")],
            [InlineKeyboardButton("🚫 Ban", callback_data="admin_ban"), InlineKeyboardButton("✅ Unban", callback_data="admin_unban")],
            back_home()
        ]
        return await query.message.edit_text(f"⚙️ **Admin Panel**\n\nTotal Users: `{count}`", reply_markup=InlineKeyboardMarkup(adm_btns))

    # Operation Logic (Requirement 1 & 2)
    if data.startswith("op_"):
        action = data.split("_")[1]
        if not USER_DATA.get(user_id, {}).get("source"):
            USER_DATA[user_id] = {"state": STATE_WAITING_PHOTO, "action": action}
            return await query.message.edit_text(f"📸 **Mode: {action.upper()}**\n\nPlease send the Image first.")
        
        USER_DATA[user_id]["action"] = action
        info = get_file_info(USER_DATA[user_id]["source"])
        
        if action == "resize":
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
                [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
                [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
                [InlineKeyboardButton("4K (3840x2160)", callback_data="res_3840x2160")],
                [InlineKeyboardButton("⌨️ Custom", callback_data="res_custom")],
                back_home()
            ])
            await query.message.edit_text(f"📐 **Resize Menu**\n\n{info}", reply_markup=markup)
        
        elif action == "compress":
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🟢 High", callback_data="comp_80"), InlineKeyboardButton("🟡 Medium", callback_data="comp_50")],
                [InlineKeyboardButton("🔴 Ultra", callback_data="comp_20")],
                back_home()
            ])
            await query.message.edit_text(f"🗜️ **Compression Menu**\n\n{info}", reply_markup=markup)

        elif action == "convert":
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
                [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
                back_home()
            ])
            await query.message.edit_text(f"✂️ **Format Converter**\n\n{info}", reply_markup=markup)
        
        elif action == "pdf":
            await process_image_pdf(client, query.message, user_id)
        
        elif action == "link":
            await process_image_link(client, query.message, user_id)

    # Sub-operation callbacks
    elif data.startswith("res_"):
        if data == "res_custom":
            USER_DATA[user_id]["state"] = STATE_WAITING_RESIZE_CUSTOM
            await query.message.edit_text("⌨️ Type dimensions: `Width Height` (e.g. `800 600`)", reply_markup=InlineKeyboardMarkup([back_home()]))
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
    if await is_banned(user_id): return
    
    # Requirement 8: Dynamic Status
    status = await message.reply_text("⏳ **Downloading...**")
    path = await message.download()
    
    # Cleanup old source if exists
    old_src = USER_DATA.get(user_id, {}).get("source")
    if old_src and os.path.exists(old_src): os.remove(old_src)
    
    USER_DATA[user_id] = USER_DATA.get(user_id, {})
    USER_DATA[user_id].update({"source": path, "state": STATE_NONE})
    
    info = get_file_info(path)
    await status.edit_text(f"✅ **Image Received!**\n\n{info}\n\nWhat tool should we use?", reply_markup=get_main_markup(user_id))

@bot.on_message(filters.text & filters.private)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state = USER_DATA.get(user_id, {}).get("state", STATE_NONE)

    if state == STATE_WAITING_RESIZE_CUSTOM:
        try:
            w, h = map(int, message.text.split())
            await process_image_resize(client, message, user_id, w, h)
        except: await message.reply_text("❌ Format: `Width Height` (e.g. `1280 720`)")

# --- CORE PROCESSING ---

async def process_image_resize(client, msg, user_id, w, h):
    path = USER_DATA[user_id]["source"]
    out = f"res_{user_id}.png"
    status = await client.send_message(user_id, "⚙️ **Processing Resize...**")
    try:
        with Image.open(path) as img:
            img.resize((w, h), Image.Resampling.LANCZOS).save(out)
        await status.edit_text("📤 **Uploading...**")
        # Requirement 6: WEBP/Sticker Fix (Force Document)
        await client.send_document(user_id, out, caption=f"✅ Resized to {w}x{h}", force_document=True)
    finally:
        await status.delete(); if os.path.exists(out): os.remove(out)

async def process_image_compress(client, msg, user_id, qual):
    path = USER_DATA[user_id]["source"]
    out = f"comp_{user_id}.jpg"
    status = await client.send_message(user_id, "⚙️ **Compressing...**")
    try:
        with Image.open(path) as img:
            img.convert("RGB").save(out, "JPEG", quality=qual, optimize=True)
        await status.edit_text("📤 **Uploading...**")
        await client.send_document(user_id, out, caption=f"✅ Quality: {qual}%", force_document=True)
    finally:
        await status.delete(); if os.path.exists(out): os.remove(out)

async def process_image_convert(client, msg, user_id, fmt):
    path = USER_DATA[user_id]["source"]
    out = f"conv_{user_id}.{fmt}"
    status = await client.send_message(user_id, f"⚙️ **Converting to {fmt.upper()}...**")
    try:
        with Image.open(path) as img:
            if fmt in ["jpg", "jpeg"]: img = img.convert("RGB")
            img.save(out)
        await status.edit_text("📤 **Uploading...**")
        await client.send_document(user_id, out, caption=f"✅ Target: {fmt.upper()}", force_document=True)
    finally:
        await status.delete(); if os.path.exists(out): os.remove(out)

async def process_image_pdf(client, msg, user_id):
    path = USER_DATA[user_id]["source"]
    out = f"doc_{user_id}.pdf"
    status = await client.send_message(user_id, "⚙️ **Creating PDF...**")
    try:
        with Image.open(path) as img:
            img.convert("RGB").save(out, "PDF")
        await status.edit_text("📤 **Uploading...**")
        await client.send_document(user_id, out, caption="✅ Image to PDF", force_document=True)
    finally:
        await status.delete(); if os.path.exists(out): os.remove(out)

async def process_image_link(client, msg, user_id):
    """Requirement 7: Proper Multipart Form Data for ImgBB"""
    path = USER_DATA[user_id]["source"]
    status = await client.send_message(user_id, "📤 **Uploading to Cloud...**")
    try:
        async with aiohttp.ClientSession() as sess:
            data = aiohttp.FormData()
            data.add_field('image', open(path, 'rb'), filename="upload.png")
            data.add_field('key', IMGBB_API_KEY)
            async with sess.post("https://api.imgbb.com/1/upload", data=data) as resp:
                res = await resp.json()
                url = res["data"]["url"]
                await client.send_message(user_id, f"✅ **Public Link Generated:**\n`{url}`", 
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open Link", url=url)]]))
    except: await client.send_message(user_id, "❌ ImgBB Upload Failed.")
    finally: await status.delete()

# --- MAIN ---
async def main():
    await start_web_server()
    await bot.start()
    logger.info("EditMediaBot Persistent Mode Online")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    try: loop.run_until_complete(main())
    except KeyboardInterrupt: pass
    finally: loop.close()
