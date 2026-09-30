import asyncio
import os
import json
import logging
import shutil
from typing import Dict

# --- CRITICAL: Python 3.14 Loop Fix ---
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# --------------------------------------

from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiohttp import web
from PIL import Image
import firebase_admin
from firebase_admin import credentials, db

# Logging Configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Environment Variables
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
FIREBASE_JSON = os.getenv("FIREBASE_JSON", "")
PORT = int(os.getenv("PORT", 8080))

# State Management constants
STATE_NONE = 0
STATE_WAITING_PHOTO = 1
STATE_WAITING_RESIZE_DIMS = 2

# In-memory user state
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

# --- DB HELPERS ---
def update_user_stats(user_id, name):
    if not firebase_admin._apps: return
    try:
        ref = db.reference(f"users/{user_id}")
        data = ref.get() or {"count": 0}
        ref.update({
            "name": name,
            "count": data.get("count", 0) + 1
        })
    except Exception as e:
        logger.error(f"DB Update Error: {e}")

# --- WEB SERVER (For Render Health Checks) ---
async def handle_health_check(request):
    return web.Response(text="Bot is alive and running!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

# --- BOT INITIALIZATION ---
bot = Client(
    "EditMediaBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- KEYBOARDS ---
START_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton("📐 Resize", callback_data="op_resize")],
    [InlineKeyboardButton("🗜️ Compress", callback_data="op_compress")],
    [InlineKeyboardButton("🔗 Public Link (Placeholder)", callback_data="op_link")]
])

# --- HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    USER_DATA[message.from_user.id] = {"state": STATE_NONE}
    await message.reply_text(
        f"Hi {message.from_user.first_name}!\n\nI am **EditMediaBot**. I can help you process images quickly.",
        reply_markup=START_MARKUP
    )

@bot.on_callback_query(filters.regex("^op_"))
async def callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    operation = query.data.split("_")[1]
    
    USER_DATA[user_id] = {"state": STATE_WAITING_PHOTO, "action": operation}
    
    await query.message.edit_text(
        f"Selected: **{operation.capitalize()}**\n\nPlease send the Image (as a Photo or Document)."
    )

@bot.on_message((filters.photo | filters.document) & filters.private)
async def media_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state_info = USER_DATA.get(user_id)

    if not state_info or state_info.get("state") != STATE_WAITING_PHOTO:
        return await message.reply_text("Please select an option from /start first.")

    status_msg = await message.reply_text("⏳ Downloading...")
    file_path = await message.download()
    
    action = state_info.get("action")
    
    try:
        if action == "compress":
            await status_msg.edit_text("🗜️ Compressing...")
            img = Image.open(file_path)
            # Convert to RGB if necessary (for RGBA/PNG to JPEG)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            output_path = f"compressed_{user_id}.jpg"
            img.save(output_path, "JPEG", quality=40, optimize=True)
            
            await message.reply_document(output_path, caption="✅ Compressed by EditMediaBot")
            os.remove(output_path)
            update_user_stats(user_id, message.from_user.first_name)
            USER_DATA[user_id]["state"] = STATE_NONE

        elif action == "resize":
            USER_DATA[user_id].update({
                "state": STATE_WAITING_RESIZE_DIMS,
                "temp_path": file_path
            })
            await status_msg.edit_text("📐 Please send dimensions in format: `width x height` (e.g., `800x600`)")
            return # Don't delete file_path yet

        elif action == "link":
            await status_msg.edit_text("🔗 Public Link feature coming soon! Processing locally instead...")
            # Logic for ImgBB or similar could be added here
        
    except Exception as e:
        logger.error(f"Processing Error: {e}")
        await message.reply_text("❌ Failed to process image.")
    finally:
        if USER_DATA[user_id].get("state") != STATE_WAITING_RESIZE_DIMS:
            if os.path.exists(file_path): os.remove(file_path)
            await status_msg.delete()

@bot.on_message(filters.text & filters.private)
async def text_handler(client: Client, message: Message):
    user_id = message.from_user.id
    state_info = USER_DATA.get(user_id)

    if state_info and state_info.get("state") == STATE_WAITING_RESIZE_DIMS:
        try:
            dims = message.text.lower().replace(" ", "").split("x")
            width, height = int(dims[0]), int(dims[1])
            
            input_path = state_info.get("temp_path")
            output_path = f"resized_{user_id}.png"
            
            img = Image.open(input_path)
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            img.save(output_path)
            
            await message.reply_document(output_path, caption=f"✅ Resized to {width}x{height}")
            
            # Cleanup
            os.remove(input_path)
            os.remove(output_path)
            USER_DATA[user_id] = {"state": STATE_NONE}
            update_user_stats(user_id, message.from_user.first_name)
            
        except Exception:
            await message.reply_text("❌ Invalid format. Please send `Width x Height` (e.g. 1280x720)")

# --- MAIN EXECUTION ---

async def main():
    # 1. Start Health Check Server
    await start_web_server()
    
    # 2. Start Pyrogram Client
    await bot.start()
    logger.info("Bot is online!")
    
    # 3. Keep the loop running until interrupted
    await idle()
    
    # 4. Graceful Shutdown
    await bot.stop()

if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
    finally:
        loop.close()
