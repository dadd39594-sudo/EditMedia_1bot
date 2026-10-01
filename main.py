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

# State Management constants
STATE_NONE = 0
STATE_WAITING_PHOTO = 1
STATE_WAITING_RESIZE_CUSTOM = 2
STATE_ADMIN_BROADCAST = 3

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
    logger.error(f"Firebase Initialization Error: {e}")

# --- HELPERS ---

async def is_subscribed(client: Client, user_id: int):
    if not CHANNELS or not CHANNELS[0]: return True
    for channel in CHANNELS:
        try:
            await client.get_chat_member(channel, user_id)
        except UserNotParticipant: return False
        except Exception: return False
    return True

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
    buttons = [
        [InlineKeyboardButton("📐 Resize", callback_data="op_resize"), InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
        [InlineKeyboardButton("🔗 Public Link", callback_data="op_link")],
        [InlineKeyboardButton("📄 Image to PDF", callback_data="op_pdf"), InlineKeyboardButton("✂️ Converter", callback_data="op_convert")]
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_main")])
    return InlineKeyboardMarkup(buttons)

def get_back_btn(callback="go_home"):
    return [InlineKeyboardButton("« Back", callback_data=callback)]

RESIZE_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
    [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
    [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
    [InlineKeyboardButton("4K (3840x2160)", callback_data="res_3840x2160")],
    [InlineKeyboardButton("⌨️ Custom Size", callback_data="res_custom")],
    get_back_btn()
])

COMPRESS_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
    [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
    [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
    get_back_btn()
])

CONVERT_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
    [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
    get_back_btn()
])

# --- HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    is_new = update_user_stats(user.id, user.first_name, user.username)
    
    if is_new and ADMIN_ID:
        await client.send_message(ADMIN_ID, f"🆕 **New User:** {user.first_name} (`{user.id}`)")

    if not await is_subscribed(client, user.id):
        return await message.reply_text("❌ **Join Channels to Continue!**", reply_markup=await get_force_sub_markup())

    text = (f"✨ **Hello {user.first_name}!**\n\n"
            "I am **EditMediaBot Premium**. Select an option below to start processing your images.")
    await message.reply_text(text, reply_markup=get_main_markup(user.id))

@bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    if data == "go_home":
        if not await is_subscribed(client, user_id):
            return await query.answer("❌ Subscribe first!", show_alert=True)
        USER_DATA[user_id] = {"state": STATE_NONE}
        return await query.message.edit_text(f"✨ **Hello {query.from_user.first_name}!**\nSelect a tool:", reply_markup=get_main_markup(user_id))

    if not await is_subscribed(client, user_id):
        return await query.message.edit_text("❌ **Access Denied!**", reply_markup=await get_force_sub_markup())

    # Operations Navigation
    if data.startswith("op_"):
        operation = data.split("_")[1]
        USER_DATA[user_id] = {"state": STATE_WAITING_PHOTO, "action": operation}
        await query.message.edit_text(
            f"💎 **Mode:** {operation.upper()}\n\n📸 Please **send the image** now.\nClick Back to cancel.",
            reply_markup=InlineKeyboardMarkup([get_back_btn()])
        )

    # Admin Logic
    elif data == "admin_main" and user_id == ADMIN_ID:
        users = db.reference("users").get()
        total = len(users) if users else 0
        await query.message.edit_text(f"⚙️ **Admin Panel**\n\nTotal Users: `{total}`", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📣 Broadcast", callback_data="admin_bc")], get_back_btn()]))

    elif data == "admin_bc" and user_id == ADMIN_ID:
        USER_DATA[user_id] = {"state": STATE_ADMIN_BROADCAST}
        await query.message.edit_text("💬 Send message to broadcast:", reply_markup=InlineKeyboardMarkup([get_back_btn()]))

    # Image Processing Callbacks
    elif data.startswith("res_"):
        if data == "res_custom":
            USER_DATA[user_id]["state"] = STATE_WAITING_RESIZE_CUSTOM
            await query.message.edit_text("⌨️ Type: `Width Height` (e.g. `800 600`)", reply_markup=InlineKeyboardMarkup([get_back_btn()]))
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
    state_info = USER_DATA.get(user_id)

    if not state_info or state_info.get("state") != STATE_WAITING_PHOTO:
        return await message.reply_text("❌ Select a mode first using /start")

    status_msg = await message.reply_text("⏳ **Downloading...**")
    file_path = await message.download()
    USER_DATA[user_id]["temp_path"] = file_path
    
    action = state_info.get("action")
    if action == "resize":
        await status_msg.edit_text("📐 **Image Received!**\nChoose a preset:", reply_markup=RESIZE_MARKUP)
    elif action == "compress":
        await status_msg.edit_text("🗜️ **Image Received!**\nChoose quality:", reply_markup=COMPRESS_MARKUP)
    elif action == "convert":
        await status_msg.edit_text("✂️ **Image Received!**\nChoose format:", reply_markup=CONVERT_MARKUP)
    elif action == "pdf":
        await process_image_pdf(client, status_msg, user_id)
    elif action == "link":
        await process_image_link(client, status_msg, user_id)

@bot.on_message(filters.text & filters.private)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state_info = USER_DATA.get(user_id)
    if not state_info: return

    if state_info.get("state") == STATE_ADMIN_BROADCAST and user_id == ADMIN_ID:
        users = db.reference("users").get()
        await message.reply_text(f"🚀 Broadcasting to {len(users)} users...")
        for uid in users:
            try: await message.copy(int(uid)); await asyncio.sleep(0.1)
            except: pass
        await message.reply_text("✅ Done.")
        USER_DATA[user_id] = {"state": STATE_NONE}

    elif state_info.get("state") == STATE_WAITING_RESIZE_CUSTOM:
        try:
            w, h = map(int, message.text.split())
            await process_image_resize(client, message, user_id, w, h)
        except: await message.reply_text("❌ Format: `Width Height` (e.g. `1280 720`)")

# --- CORE LOGIC ---

async def process_image_resize(client, msg, user_id, w, h):
    path = USER_DATA[user_id].get("temp_path")
    out = f"res_{user_id}.png"
    status = await client.send_message(user_id, "⚙️ **Processing Resize...**")
    try:
        img = Image.open(path)
        img.resize((w, h), Image.Resampling.LANCZOS).save(out)
        await status.edit_text("📤 **Uploading...**")
        await client.send_document(user_id, out, caption=f"✅ Resized to {w}x{h}", force_document=True)
    finally:
        await status.delete(); cleanup([path, out], user_id)

async def process_image_compress(client, msg, user_id, qual):
    path = USER_DATA[user_id].get("temp_path")
    out = f"comp_{user_id}.jpg"
    status = await client.send_message(user_id, "⚙️ **Compressing...**")
    try:
        Image.open(path).convert("RGB").save(out, "JPEG", quality=qual, optimize=True)
        await status.edit_text("📤 **Uploading...**")
        await client.send_document(user_id, out, caption=f"✅ Quality: {qual}%", force_document=True)
    finally:
        await status.delete(); cleanup([path, out], user_id)

async def process_image_convert(client, msg, user_id, fmt):
    path = USER_DATA[user_id].get("temp_path")
    out = f"conv_{user_id}.{fmt}"
    status = await client.send_message(user_id, f"⚙️ **Converting to {fmt.upper()}...**")
    try:
        img = Image.open(path)
        if fmt in ["jpg", "jpeg"]: img = img.convert("RGB")
        img.save(out)
        await status.edit_text("📤 **Uploading...**")
        # Fix Bug 3: Force Document
        await client.send_document(user_id, out, caption=f"✅ Format: {fmt.upper()}", force_document=True)
    finally:
        await status.delete(); cleanup([path, out], user_id)

async def process_image_pdf(client, msg, user_id):
    path = USER_DATA[user_id].get("temp_path")
    out = f"doc_{user_id}.pdf"
    await msg.edit_text("⚙️ **Converting to PDF...**")
    try:
        Image.open(path).convert("RGB").save(out, "PDF")
        await msg.edit_text("📤 **Uploading...**")
        await client.send_document(user_id, out, caption="✅ PDF Generated", force_document=True)
    finally:
        await msg.delete(); cleanup([path, out], user_id)

async def process_image_link(client, msg, user_id):
    path = USER_DATA[user_id].get("temp_path")
    await msg.edit_text("📤 **Uploading to Cloud...**")
    try:
        async with aiohttp.ClientSession() as sess:
            # Fix Bug 4: Proper Multipart Form Data
            data = aiohttp.FormData()
            data.add_field('image', open(path, 'rb'))
            data.add_field('key', IMGBB_API_KEY)
            async with sess.post("https://api.imgbb.com/1/upload", data=data) as resp:
                res = await resp.json()
                url = res["data"]["url"]
                await client.send_message(user_id, f"✅ **Public Link:**\n`{url}`", 
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open Link", url=url)]]))
    except: await client.send_message(user_id, "❌ ImgBB Upload Failed.")
    finally:
        await msg.delete(); cleanup([path], user_id)

def cleanup(files, user_id):
    for f in files:
        if f and os.path.exists(f): os.remove(f)
    USER_DATA[user_id] = {"state": STATE_NONE}

# --- MAIN ---
async def main():
    await start_web_server()
    await bot.start()
    logger.info("Bot Online")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    try: loop.run_until_complete(main())
    except KeyboardInterrupt: pass
    finally: loop.close()
