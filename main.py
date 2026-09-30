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
CHANNELS = os.getenv("CHANNELS", "").replace(" ", "").split(",") # Format: -100xxx,@channel
PORT = int(os.getenv("PORT", 8080))

# State Management constants
STATE_NONE = 0
STATE_WAITING_PHOTO = 1
STATE_WAITING_RESIZE_CUSTOM = 2
STATE_ADMIN_BROADCAST = 3

# In-memory user data tracking
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
    else:
        logger.warning("FIREBASE_JSON not found. Database features will be disabled.")
except Exception as e:
    logger.error(f"Firebase Initialization Error: {e}")

# --- HELPERS ---

async def is_subscribed(client: Client, user_id: int):
    """Checks if the user is subscribed to all mandatory channels."""
    if not CHANNELS or not CHANNELS[0]:
        return True
    for channel in CHANNELS:
        try:
            await client.get_chat_member(channel, user_id)
        except UserNotParticipant:
            return False
        except Exception as e:
            logger.error(f"Force Sub Error: {e}")
    return True

async def get_force_sub_markup():
    buttons = []
    for i, channel in enumerate(CHANNELS, 1):
        url = f"https://t.me/{channel.replace('@','')}" if "@" in channel else f"https://t.me/c/{channel.replace('-100','')}/1"
        buttons.append([InlineKeyboardButton(f"📢 Join Channel {i}", url=url)])
    buttons.append([InlineKeyboardButton("🔄 Check Subscription", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

def update_user_stats(user_id, name, username=None):
    if not firebase_admin._apps: return False
    try:
        ref = db.reference(f"users/{user_id}")
        data = ref.get()
        is_new = data is None
        ref.update({
            "name": name,
            "username": username,
            "count": (data.get("count", 0) if data else 0) + 1
        })
        return is_new
    except Exception as e:
        logger.error(f"DB Update Error: {e}")
        return False

# --- WEB SERVER ---
async def handle_health_check(request):
    return web.Response(text="EditMediaBot is Online", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# --- BOT INITIALIZATION ---
bot = Client("EditMediaBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- KEYBOARDS ---
def get_main_markup(user_id):
    buttons = [
        [InlineKeyboardButton("📐 Resize", callback_data="op_resize"), InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
        [InlineKeyboardButton("🔗 Public Link", callback_data="op_link")],
        [InlineKeyboardButton("📄 Image to PDF", callback_data="op_pdf"), InlineKeyboardButton("✂️ Converter", callback_data="op_convert")]
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_main")])
    return InlineKeyboardMarkup(buttons)

RESIZE_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
    [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
    [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
    [InlineKeyboardButton("4K (3840x2110)", callback_data="res_3840x2110")],
    [InlineKeyboardButton("⌨️ Custom Size", callback_data="res_custom")]
])

COMPRESS_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
    [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
    [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")]
])

CONVERT_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
    [InlineKeyboardButton("WEBP", callback_data="conv_webp")]
])

# --- HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    is_new = update_user_stats(user.id, user.first_name, user.username)
    
    # Notify Admin of new user
    if is_new and ADMIN_ID:
        await client.send_message(ADMIN_ID, f"🆕 **New User Started Bot!**\n\n👤 Name: {user.first_name}\n🆔 ID: `{user.id}`\n🔗 Username: @{user.username or 'N/A'}")

    if not await is_subscribed(client, user.id):
        return await message.reply_text("❌ **Access Denied!**\n\nYou must join our update channels to use this bot.", reply_markup=await get_force_sub_markup())

    text = (f"✨ **Hello {user.first_name}!**\n\n"
            "Welcome to **EditMediaBot Premium**. I am a high-speed image processor.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💡 **Available Tools:**\n"
            "• Resize to any dimension\n"
            "• Advanced Compression\n"
            "• Cloud Public Links\n"
            "• Format Conversion\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 Select an option to begin:")
    
    await message.reply_text(text, reply_markup=get_main_markup(user.id))

@bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    # Force Sub Check
    if data == "check_sub":
        if await is_subscribed(client, user_id):
            await query.answer("✅ Thank you for joining!", show_alert=True)
            return await start_cmd(client, query.message)
        else:
            return await query.answer("❌ You haven't joined yet!", show_alert=True)

    if not await is_subscribed(client, user_id):
        return await query.message.edit_text("❌ **Access Denied! Join channels first.**", reply_markup=await get_force_sub_markup())

    # Operations
    if data.startswith("op_"):
        operation = data.split("_")[1]
        USER_DATA[user_id] = {"state": STATE_WAITING_PHOTO, "action": operation}
        await query.message.edit_text(f"💎 **Mode:** {operation.upper()}\n\n📸 Please **send the image** you want to process.")

    # Admin Panel
    elif data == "admin_main" and user_id == ADMIN_ID:
        users = db.reference("users").get()
        total = len(users) if users else 0
        await query.message.edit_text(f"⚙️ **Admin Panel**\n\nTotal Users: `{total}`", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📣 Broadcast", callback_data="admin_bc")]]))

    elif data == "admin_bc" and user_id == ADMIN_ID:
        USER_DATA[user_id] = {"state": STATE_ADMIN_BROADCAST}
        await query.message.edit_text("💬 Send the message you want to broadcast to all users.")

    # Resize Presets
    elif data.startswith("res_"):
        if data == "res_custom":
            USER_DATA[user_id]["state"] = STATE_WAITING_RESIZE_CUSTOM
            await query.message.edit_text("⌨️ Please type dimensions as: `Width Height` (e.g., `800 600`)")
        else:
            dims = data.split("_")[1].split("x")
            await process_image_resize(client, query.message, user_id, int(dims[0]), int(dims[1]))

    # Compression Presets
    elif data.startswith("comp_"):
        quality = int(data.split("_")[1])
        await process_image_compress(client, query.message, user_id, quality)

    # Conversion Presets
    elif data.startswith("conv_"):
        fmt = data.split("_")[1]
        await process_image_convert(client, query.message, user_id, fmt)

@bot.on_message((filters.photo | filters.document) & filters.private)
async def media_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if not await is_subscribed(client, user_id):
        return await message.reply_text("❌ Join channels first!", reply_markup=await get_force_sub_markup())

    state_info = USER_DATA.get(user_id)
    if not state_info or state_info.get("state") != STATE_WAITING_PHOTO:
        return await message.reply_text("❌ Select an option from /start first.")

    status_msg = await message.reply_text("⏳ **Downloading...**")
    file_path = await message.download()
    USER_DATA[user_id]["temp_path"] = file_path
    
    action = state_info.get("action")
    if action == "resize":
        await status_msg.edit_text("📐 Choose Resize Preset:", reply_markup=RESIZE_MARKUP)
    elif action == "compress":
        await status_msg.edit_text("🗜️ Choose Compression Level:", reply_markup=COMPRESS_MARKUP)
    elif action == "convert":
        await status_msg.edit_text("✂️ Choose Target Format:", reply_markup=CONVERT_MARKUP)
    elif action == "pdf":
        await process_image_pdf(client, status_msg, user_id)
    elif action == "link":
        await process_image_link(client, status_msg, user_id)

@bot.on_message(filters.text & filters.private)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state_info = USER_DATA.get(user_id)
    if not state_info: return

    # Admin Broadcast
    if state_info.get("state") == STATE_ADMIN_BROADCAST and user_id == ADMIN_ID:
        users = db.reference("users").get()
        count = 0
        await message.reply_text("🚀 Starting Broadcast...")
        for uid in users:
            try:
                await message.copy(int(uid))
                count += 1
                await asyncio.sleep(0.1)
            except: pass
        await message.reply_text(f"✅ Broadcast Finished. Sent to `{count}` users.")
        USER_DATA[user_id] = {"state": STATE_NONE}

    # Custom Resize
    elif state_info.get("state") == STATE_WAITING_RESIZE_CUSTOM:
        try:
            parts = message.text.split()
            w, h = int(parts[0]), int(parts[1])
            await process_image_resize(client, message, user_id, w, h)
        except:
            await message.reply_text("❌ Invalid format. Use: `Width Height` (e.g., `1280 720`)")

# --- CORE PROCESSING LOGIC ---

async def process_image_resize(client, msg, user_id, w, h):
    path = USER_DATA[user_id].get("temp_path")
    out = f"resize_{user_id}.png"
    try:
        img = Image.open(path)
        img = img.resize((w, h), Image.Resampling.LANCZOS)
        img.save(out)
        await client.send_document(user_id, out, caption=f"✅ Resized to {w}x{h}")
    finally:
        cleanup([path, out], user_id)

async def process_image_compress(client, msg, user_id, qual):
    path = USER_DATA[user_id].get("temp_path")
    out = f"comp_{user_id}.jpg"
    try:
        img = Image.open(path).convert("RGB")
        img.save(out, "JPEG", quality=qual, optimize=True)
        await client.send_document(user_id, out, caption=f"✅ Compressed (Quality: {qual}%)")
    finally:
        cleanup([path, out], user_id)

async def process_image_convert(client, msg, user_id, fmt):
    path = USER_DATA[user_id].get("temp_path")
    out = f"conv_{user_id}.{fmt}"
    try:
        img = Image.open(path)
        if fmt.lower() in ["jpg", "jpeg"]: img = img.convert("RGB")
        img.save(out)
        await client.send_document(user_id, out, caption=f"✅ Converted to {fmt.upper()}")
    finally:
        cleanup([path, out], user_id)

async def process_image_pdf(client, msg, user_id):
    path = USER_DATA[user_id].get("temp_path")
    out = f"converted_{user_id}.pdf"
    try:
        img = Image.open(path).convert("RGB")
        img.save(out, "PDF", resolution=100.0)
        await client.send_document(user_id, out, caption="✅ Converted to PDF")
    finally:
        cleanup([path, out], user_id)

async def process_image_link(client, msg, user_id):
    path = USER_DATA[user_id].get("temp_path")
    try:
        async with aiohttp.ClientSession() as session:
            with open(path, "rb") as f:
                data = {"image": f, "key": IMGBB_API_KEY}
                async with session.post("https://api.imgbb.com/1/upload", data=data) as resp:
                    res = await resp.json()
                    url = res["data"]["url"]
                    btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open Link", url=url)]])
                    await client.send_message(user_id, f"✅ **Public Link Generated:**\n`{url}`", reply_markup=btn)
    finally:
        cleanup([path], user_id)

def cleanup(files, user_id):
    for f in files:
        if f and os.path.exists(f): os.remove(f)
    USER_DATA[user_id] = {"state": STATE_NONE}

# --- MAIN EXECUTION ---
async def main():
    await start_web_server()
    await bot.start()
    logger.info("Premium EditMediaBot is Online!")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
    finally:
        loop.close()
