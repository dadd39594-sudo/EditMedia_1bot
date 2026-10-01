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
DATABASE_URL = os.getenv("DATABASE_URL", "")  # Requirement 1: New Env Var
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")
CHANNELS = os.getenv("CHANNELS", "").replace(" ", "").split(",")
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
        # Requirement 2: Bulletproof URL Resolution
        db_url = DATABASE_URL or cert_dict.get('databaseURL') or f"https://{cert_dict['project_id']}-default-rtdb.firebaseio.com/"
        firebase_admin.initialize_app(cred, {'databaseURL': db_url})
        logger.info(f"Firebase successfully initialized with URL: {db_url}")
    else:
        logger.warning("FIREBASE_JSON missing. Database features will be disabled.")
except Exception as e:
    logger.error(f"CRITICAL FIREBASE INIT ERROR: {e}")

# --- HELPERS & UI GENERATORS ---

async def is_subscribed(client: Client, user_id: int):
    if not CHANNELS or not CHANNELS[0]: return True
    for channel in CHANNELS:
        try:
            await client.get_chat_member(channel, user_id)
        except UserNotParticipant: return False
        except Exception: return False
    return True

async def is_banned(user_id: int):
    """Requirement 3: Wrapped Firebase Call"""
    try:
        # Check if Firebase is even initialized
        if not firebase_admin._apps: return False
        return db.reference(f"banned/{user_id}").get() is True
    except Exception as e:
        logger.error(f"Firebase is_banned Error: {e}")
        return False # Fallback: Allow access if DB fails

def get_welcome_layout(user_id, first_name):
    source = USER_DATA.get(user_id, {}).get("source")
    if not source or not os.path.exists(source):
        text = (f"✨ **Hello {first_name}!**\n\n"
                "I am **EditMediaBot Premium**. I can resize, compress, and convert your images with elite precision.\n\n"
                "👇 **To begin, select a tool and send an image:**")
    else:
        info = "Error reading image"
        try:
            with Image.open(source) as img:
                w, h = img.size
                fmt = img.format
            size_bytes = os.path.getsize(source)
            size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1048576 else f"{size_bytes / 1048576:.2f} MB"
            info = f"📏 **Resolution:** {w}x{h}\n📄 **Format:** {fmt}\n🗂️ **Size:** {size_str}"
        except: pass
        text = (f"✨ **Welcome Back, {first_name}!**\n\n"
                f"✅ **Active Image Details:**\n{info}\n\n"
                "👇 **Choose a tool to apply to this image:**")
    return text

def get_main_buttons(user_id):
    has_photo = USER_DATA.get(user_id, {}).get("source") is not None
    btns = [
        [InlineKeyboardButton("📐 Resize", callback_data="op_resize"), 
         InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
        [InlineKeyboardButton("🔗 Create Public Link", callback_data="op_link")],
        [InlineKeyboardButton("📄 Image to PDF", callback_data="op_pdf"), 
         InlineKeyboardButton("✂️ Format Converter", callback_data="op_convert")]
    ]
    if has_photo:
        btns.append([InlineKeyboardButton("🔄 Change Active Photo", callback_data="ask_photo")])
    if user_id == ADMIN_ID:
        btns.append([InlineKeyboardButton("⚙️ Admin Dashboard", callback_data="admin_main")])
    return InlineKeyboardMarkup(btns)

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
    if await is_banned(user_id): return
    
    # Requirement 3 & 4: Wrapped User Registration
    try:
        if firebase_admin._apps:
            db_ref = db.reference(f"users/{user_id}")
            if not db_ref.get():
                db_ref.set({"name": message.from_user.first_name, "username": message.from_user.username})
                if ADMIN_ID: 
                    try: await client.send_message(ADMIN_ID, f"🆕 **New User:** {message.from_user.first_name} (`{user_id}`)")
                    except: pass
    except Exception as e:
        logger.error(f"Firebase Register Error (Non-Fatal): {e}")

    if not await is_subscribed(client, user_id):
        buttons = []
        for i, channel in enumerate(CHANNELS, 1):
            url = f"https://t.me/{channel.replace('@','')}" if "@" in channel else f"https://t.me/c/{channel.replace('-100','')}/1"
            buttons.append([InlineKeyboardButton(f"📢 Join Channel {i}", url=url)])
        buttons.append([InlineKeyboardButton("🔄 Check Subscription", callback_data="go_home")])
        return await message.reply_text("❌ **Access Denied!**", reply_markup=InlineKeyboardMarkup(buttons))

    await message.reply_text(get_welcome_layout(user_id, message.from_user.first_name), reply_markup=get_main_buttons(user_id))

@bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    if await is_banned(user_id): return await query.answer("Banned.", show_alert=True)
    data = query.data

    if data == "go_home":
        USER_DATA[user_id] = USER_DATA.get(user_id, {"state": STATE_NONE})
        USER_DATA[user_id]["state"] = STATE_NONE
        return await query.message.edit_text(get_welcome_layout(user_id, query.from_user.first_name), reply_markup=get_main_buttons(user_id))

    if data == "ask_photo":
        USER_DATA[user_id]["state"] = STATE_WAITING_PHOTO
        return await query.message.edit_text("📸 **Please send the new Image.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="go_home")]]))

    # Admin Dashboard Logic (Wrapped)
    if data == "admin_main" and user_id == ADMIN_ID:
        count = "N/A"
        try:
            if firebase_admin._apps:
                users = db.reference("users").get()
                count = len(users) if users else 0
        except Exception as e:
            logger.error(f"Firebase Stats Error: {e}")
            count = "Offline"
        
        text = f"⚙️ **Admin Dashboard**\n\n📊 Total Users: `{count}`\n\nManage your bot and users below:"
        btns = [
            [InlineKeyboardButton("📣 Broadcast Message", callback_data="admin_bc")],
            [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"), InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")],
            [InlineKeyboardButton("« Back to Menu", callback_data="go_home")]
        ]
        return await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns))

    if data in ["admin_bc", "admin_ban", "admin_unban"] and user_id == ADMIN_ID:
        state_map = {"admin_bc": STATE_ADMIN_BROADCAST, "admin_ban": STATE_ADMIN_BAN, "admin_unban": STATE_ADMIN_UNBAN}
        USER_DATA[user_id] = {"state": state_map[data]}
        return await query.message.edit_text("💬 **Waiting for your input...**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="admin_main")]]))

    # Tools logic
    if data.startswith("op_"):
        action = data.split("_")[1]
        if not USER_DATA.get(user_id, {}).get("source"):
            USER_DATA[user_id] = {"state": STATE_WAITING_PHOTO, "action": action}
            return await query.message.edit_text(f"💎 **Mode: {action.upper()}**\n\nPlease send the Image now.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="go_home")]]))
        
        USER_DATA[user_id]["action"] = action
        if action == "resize":
            btns = [[InlineKeyboardButton("Square (1080x1080)", callback_data="res_1080x1080")],
                    [InlineKeyboardButton("HD (1280x720)", callback_data="res_1280x720")],
                    [InlineKeyboardButton("Full HD (1920x1080)", callback_data="res_1920x1080")],
                    [InlineKeyboardButton("4K (3840x2160)", callback_data="res_3840x2160")],
                    [InlineKeyboardButton("⌨️ Custom Size", callback_data="res_custom")],
                    [InlineKeyboardButton("« Back", callback_data="go_home")]]
            await query.message.edit_text("📐 **Choose Resize Preset:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "compress":
            btns = [[InlineKeyboardButton("🟢 High Quality", callback_data="comp_80")],
                    [InlineKeyboardButton("🟡 Medium Quality", callback_data="comp_50")],
                    [InlineKeyboardButton("🔴 Ultra Compress", callback_data="comp_20")],
                    [InlineKeyboardButton("« Back", callback_data="go_home")]]
            await query.message.edit_text("🗜️ **Choose Quality:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "convert":
            btns = [[InlineKeyboardButton("PNG", callback_data="conv_png"), InlineKeyboardButton("JPG", callback_data="conv_jpeg")],
                    [InlineKeyboardButton("WEBP", callback_data="conv_webp")],
                    [InlineKeyboardButton("« Back", callback_data="go_home")]]
            await query.message.edit_text("✂️ **Choose Format:**", reply_markup=InlineKeyboardMarkup(btns))
        elif action == "pdf": await process_image_pdf(client, query.message, user_id)
        elif action == "link": await process_image_link(client, query.message, user_id)

    elif data.startswith("res_"):
        if data == "res_custom":
            USER_DATA[user_id]["state"] = STATE_WAITING_RESIZE_CUSTOM
            await query.message.edit_text("⌨️ Type: `Width Height` (e.g. `800 600`)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="go_home")]]))
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
    status = await message.reply_text("⏳ **Downloading Image...**")
    path = await message.download()
    old_src = USER_DATA.get(user_id, {}).get("source")
    if old_src and os.path.exists(old_src):
        try: os.remove(old_src)
        except: pass
    USER_DATA[user_id] = USER_DATA.get(user_id, {})
    USER_DATA[user_id].update({"source": path, "state": STATE_NONE})
    await status.edit_text(get_welcome_layout(user_id, message.from_user.first_name), reply_markup=get_main_buttons(user_id))

@bot.on_message(filters.text & filters.private)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state = USER_DATA.get(user_id, {}).get("state", STATE_NONE)

    if user_id == ADMIN_ID:
        if state == STATE_ADMIN_BROADCAST:
            try:
                users = db.reference("users").get()
                if not users: raise Exception("No users in DB")
                status = await message.reply_text("🚀 **Broadcasting...**")
                count = 0
                for uid in users:
                    try:
                        await message.copy(int(uid))
                        count += 1
                        await asyncio.sleep(0.05)
                    except: pass
                await status.edit_text(f"✅ **Broadcast Done!** Sent to `{count}` users.")
            except Exception as e:
                await message.reply_text(f"❌ Broadcast Failed: {e}")
            USER_DATA[user_id]["state"] = STATE_NONE

        elif state == STATE_ADMIN_BAN:
            try:
                db.reference(f"banned/{message.text}").set(True)
                await message.reply_text(f"🚫 User `{message.text}` Banned.")
            except Exception as e: await message.reply_text(f"❌ Ban Failed: {e}")
            USER_DATA[user_id]["state"] = STATE_NONE

        elif state == STATE_ADMIN_UNBAN:
            try:
                db.reference(f"banned/{message.text}").delete()
                await message.reply_text(f"✅ User `{message.text}` Unbanned.")
            except Exception as e: await message.reply_text(f"❌ Unban Failed: {e}")
            USER_DATA[user_id]["state"] = STATE_NONE

    if state == STATE_WAITING_RESIZE_CUSTOM:
        try:
            w, h = map(int, message.text.split())
            await process_image_resize(client, message, user_id, w, h)
        except: await message.reply_text("❌ Format: `Width Height` (e.g. `1280 720`)")

# --- CORE LOGIC ---

async def process_image_resize(client, msg, user_id, w, h):
    path = USER_DATA[user_id]["source"]
    out = f"res_{user_id}.png"
    status = await client.send_message(user_id, "⚙️ **Processing Resize...**")
    try:
        with Image.open(path) as img:
            img.resize((w, h), Image.Resampling.LANCZOS).save(out)
        await status.edit_text("📤 **Uploading Result...**")
        await client.send_document(user_id, out, caption=f"✅ Resized to {w}x{h}", force_document=True)
    finally:
        try: await status.delete()
        except: pass
        if os.path.exists(out): os.remove(out)

async def process_image_compress(client, msg, user_id, qual):
    path = USER_DATA[user_id]["source"]
    out = f"comp_{user_id}.jpg"
    status = await client.send_message(user_id, "⚙️ **Compressing Image...**")
    try:
        with Image.open(path) as img:
            img.convert("RGB").save(out, "JPEG", quality=qual, optimize=True)
        await status.edit_text("📤 **Uploading Result...**")
        await client.send_document(user_id, out, caption=f"✅ Quality: {qual}%", force_document=True)
    finally:
        try: await status.delete()
        except: pass
        if os.path.exists(out): os.remove(out)

async def process_image_convert(client, msg, user_id, fmt):
    path = USER_DATA[user_id]["source"]
    out = f"conv_{user_id}.{fmt}"
    status = await client.send_message(user_id, f"⚙️ **Converting to {fmt.upper()}...**")
    try:
        with Image.open(path) as img:
            if fmt in ["jpg", "jpeg"]: img = img.convert("RGB")
            img.save(out)
        await status.edit_text("📤 **Uploading Result...**")
        await client.send_document(user_id, out, caption=f"✅ Target: {fmt.upper()}", force_document=True)
    finally:
        try: await status.delete()
        except: pass
        if os.path.exists(out): os.remove(out)

async def process_image_pdf(client, msg, user_id):
    path = USER_DATA[user_id]["source"]
    out = f"doc_{user_id}.pdf"
    status = await client.send_message(user_id, "⚙️ **Creating PDF...**")
    try:
        with Image.open(path) as img:
            img.convert("RGB").save(out, "PDF")
        await status.edit_text("📤 **Uploading Result...**")
        await client.send_document(user_id, out, caption="✅ PDF Generated", force_document=True)
    finally:
        try: await status.delete()
        except: pass
        if os.path.exists(out): os.remove(out)

async def process_image_link(client, msg, user_id):
    path = USER_DATA[user_id]["source"]
    status = await client.send_message(user_id, "📤 **Generating Public Link...**")
    try:
        with open(path, "rb") as img_file:
            b64_str = base64.b64encode(img_file.read()).decode('utf-8')
        async with aiohttp.ClientSession() as sess:
            data = aiohttp.FormData()
            data.add_field('image', b64_str)
            data.add_field('key', IMGBB_API_KEY)
            async with sess.post("https://api.imgbb.com/1/upload", data=data) as resp:
                res = await resp.json()
                url = res["data"]["url"]
                await client.send_message(user_id, f"✅ **Public Link Generated:**\n`{url}`", 
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open Link", url=url)]]))
    except: await client.send_message(user_id, "❌ ImgBB Upload Failed.")
    finally: 
        try: await status.delete()
        except: pass

# --- MAIN ---
async def main():
    await start_web_server()
    await bot.start()
    logger.info("EditMediaBot Stable Mode Online")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    try: loop.run_until_complete(main())
    except KeyboardInterrupt: pass
    finally: loop.close()
