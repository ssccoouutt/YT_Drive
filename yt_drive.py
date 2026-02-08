import os
import logging
import re
import tempfile
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)
from yt_dlp import YoutubeDL
from aiohttp import web  # Added missing import

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7966314098:AAEuW6yHTblcJXhG3AA915_geQtju4ck37c")
COOKIES_FILE = os.getenv('COOKIES_FILE', 'cookies.txt')  # Optional for restricted videos
PORT = int(os.getenv('PORT', 8000))

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables to store context
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📺 YouTube Video Downloader Bot\n\n"
        "Send me any YouTube link and I'll download it for you!\n\n"
        "Supported:\n"
        "- Videos\n"
        "- Shorts\n"
        "- Playlists\n\n"
        "Note: Some videos may require cookies for download"
    )

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    # Validate URL
    if not re.match(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+', url):
        await update.message.reply_text("❌ Please send a valid YouTube URL")
        return
    
    # Store URL in user data
    user_data[update.effective_user.id] = {'url': url}
    
    # Create resolution selection keyboard (only progressive formats that don't need merging)
    keyboard = [
        [
            InlineKeyboardButton("360p", callback_data="360"),
            InlineKeyboardButton("480p", callback_data="480"),
        ],
        [
            InlineKeyboardButton("720p", callback_data="720"),
            InlineKeyboardButton("Best Available", callback_data="best"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎬 Select video quality (higher qualities may not be available for all videos):",
        reply_markup=reply_markup
    )

async def handle_resolution_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    resolution = query.data
    
    if user_id not in user_data or 'url' not in user_data[user_id]:
        await query.edit_message_text("❌ Session expired. Please send the YouTube link again.")
        return
    
    url = user_data[user_id]['url']
    
    await query.edit_message_text(f"⬇️ Downloading video in {resolution}p...")
    
    try:
        file_path, title = await download_youtube_video(url, resolution)
        
        await query.message.reply_text("📤 Uploading to Telegram...")
        with open(file_path, 'rb') as video_file:
            await query.message.reply_video(
                video=video_file,
                caption=f"🎥 {title}\nQuality: {resolution}p",
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=120
            )
        
        os.remove(file_path)
    except Exception as e:
        error_msg = str(e)
        if 'ffmpeg' in error_msg:
            error_msg = "This video format requires ffmpeg which is not available. Try a lower quality."
        elif 'bot' in error_msg:
            error_msg += "\n\n⚠️ YouTube is asking for verification. Try again later or use a different video."
        await query.message.reply_text(f"❌ Error: {error_msg}")

async def download_youtube_video(url, resolution):
    # Check if cookies file exists
    cookies_available = os.path.exists(COOKIES_FILE)
    logger.info(f"Cookies file available: {cookies_available} | Path: {COOKIES_FILE}")
    
    # Format selection - only progressive formats that don't need merging
    format_map = {
        '360': 'bestvideo[ext=mp4][height<=360]+bestaudio[ext=m4a]/best[ext=mp4][height<=360]',
        '480': 'bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]/best[ext=mp4][height<=480]',
        '720': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]',
        'best': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]'
    }
    
    ydl_opts = {
        'format': format_map.get(resolution, 'best[ext=mp4]'),
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),
        'quiet': False,
        'cookiefile': COOKIES_FILE if cookies_available else None,
        'extract_flat': False,
        'logger': logger,
        # Disable formats that require merging
        'merge_output_format': None,
        'prefer_free_formats': True,
        # Android-specific optimizations
        'android': True,
        'no_part': True,
        'ignoreerrors': True,
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            logger.info(f"Successfully downloaded: {file_path}")
            return file_path, info['title']
    except Exception as e:
        logger.error(f"YouTube download failed: {str(e)}")
        raise Exception(f"Failed to download video. {'Try a lower quality.' if 'ffmpeg' in str(e) else str(e)}")

async def health_check(request):
    return web.Response(text="🤖 Bot is running")

async def run_webserver():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Health check running on port {PORT}")
    return runner

async def main():
    # Start webserver for Railway health checks
    runner = await run_webserver()
    
    # Start Telegram bot
    bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
    bot.add_handler(CallbackQueryHandler(handle_resolution_selection))
    
    await bot.initialize()
    await bot.start()
    logger.info("Bot is running and ready")
    
    # Keep running
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        # Verify cookies file exists
        if not os.path.exists(COOKIES_FILE):
            logger.warning("⚠️ cookies.txt not found! Some videos may not download without it")
        
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Bot crashed: {str(e)}")
