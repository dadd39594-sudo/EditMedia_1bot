import os
import json
import asyncio
import logging
from typing import Dict

import aiohttp
from PIL import Image
from pyrogram import Client, filters, types
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import firebase_admin
from firebase_admin import credentials, db
from aiohttp import web

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")
FIREBASE_JSON = os.getenv("FIREBASE_JSON")  # Raw JSON string
PORT = int(os.getenv("PORT", 8080))

# Temporary User State Storage (Memory-based for speed, synced to Firebase for stats)
user_states: Dict[int, Dict] = {}

# --- FIREBASE INITIALIZATION ---
try:
    cred_dict = json.loads(FIREBASE_JSON)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {
        'databaseURL': f'https://{cred_dict["project_id"]}-default-rtdb.firebaseio.com/'
    })
    db_ref = db.reference("/users")
    logger.info("Firebase initialized successfully.")
except Exception as e:
    logger.error(f"Firebase Init Error: {e}")
    db_ref = None

# --- DATABASE LOGIC ---
async def update_user_stats(user: types.User):
    """Updates user info and increments image processed count."""
    if not db_ref: return
    user_id = str(user.id)
    user_data = db_ref.child(user_id).get()
    
    if user_data:
        count = user_data.get("processed_count", 0) + 1
        db_ref.child(user_id).update({
            "first_name": user.first_name,
            "processed_count": count
        })
    else:
        db_ref.child(user_id).set({
            "first_name": user.first_name,
            "processed_count": 1
        })

# --- IMAGE PROCESSING LOGIC ---
async def upload_to_imgbb(file_path: str) -> str:
    """Uploads an image to ImgBB and returns the URL."""
    async with aiohttp.ClientSession() as session:
        with open(file_path, "rb") as f:
            data = {"image": f, "key": IMGBB_API_KEY}
            async with session.post("https://api.imgbb.com/1/upload", data=data) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    return res_json["data"]["url"]
                return None

# --- BOT HANDLERS ---
bot = Client("EditMediaBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    text = f"Hello {message.from_user.mention}!\nI am EditMediaBot. How can I help you today?"
    buttons = [
        [InlineKeyboardButton("📐 Resize", callback_data="mode_resize")],
        [InlineKeyboardButton("🗜️ Compress", callback_data="mode_compress")],
        [InlineKeyboardButton("🔗 Create Public Link", callback_data="mode_link")]
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex(r"^mode_"))
async def callback_handler(client, callback_query):
    mode = callback_query.data.split("_")[1]
    user_id = callback_query.from_user.id
    
    user_states[user_id] = {"mode": mode}
    
    text = {
        "resize": "Upload the image you want to **Resize**.",
        "compress": "Upload the image you want to **Compress**.",
        "link": "Upload the image to generate a **Public Link**."
    }
    
    await callback_query.message.edit_text(text[mode])

@bot.on_message(filters.photo | filters.document)
async def media_handler(client, message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if not state:
        return await message.reply_text("Please select an option from /start first.")

    msg = await message.reply_text("📥 Downloading media...")
    file_path = await message.download()
    
    try:
        if state["mode"] == "resize":
            user_states[user_id]["file_path"] = file_path
            await msg.edit_text("Send the dimensions in format: `Width x Height` (e.g., 800x600)")
            user_states[user_id]["waiting_for_dims"] = True
            return # Wait for next message

        elif state["mode"] == "compress":
            await msg.edit_text("🗜️ Compressing...")
            img = Image.open(file_path)
            out_path = f"compressed_{user_id}.jpg"
            img.save(out_path, "JPEG", quality=30, optimize=True)
            await message.reply_document(out_path, caption="✅ Compressed Image")
            os.remove(out_path)

        elif state["mode"] == "link":
            await msg.edit_text("🔗 Generating Link...")
            url = await upload_to_imgbb(file_path)
            if url:
                await message.reply_text(f"✅ **Public Link:**\n`{url}`", disable_web_page_preview=True)
            else:
                await message.reply_text("❌ Failed to upload to ImgBB.")

        await update_user_stats(message.from_user)
        user_states.pop(user_id, None)

    except Exception as e:
        logger.error(f"Error: {e}")
        await message.reply_text("❌ An error occurred during processing.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        await msg.delete()

@bot.on_message(filters.text & ~filters.command("start"))
async def text_handler(client, message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if state and state.get("waiting_for_dims"):
        try:
            dims = message.text.lower().split("x")
            width, height = int(dims[0]), int(dims[1])
            file_path = state["file_path"]

            msg = await message.reply_text("📐 Resizing...")
            img = Image.open(file_path)
            resized_img = img.resize((width, height), Image.LANCZOS)
            
            out_path = f"resized_{user_id}.png"
            resized_img.save(out_path)
            
            await message.reply_document(out_path, caption=f"✅ Resized to {width}x{height}")
            
            os.remove(out_path)
            os.remove(file_path)
            await update_user_stats(message.from_user)
            user_states.pop(user_id, None)
            await msg.delete()
        except Exception:
            await message.reply_text("❌ Invalid format. Please send like: `800x600`")

# --- WEB SERVER FOR HEALTH CHECKS ---
async def handle_hc(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_hc)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_web_server())
    logger.info("Starting Bot...")
    bot.run()
