import os
import logging
import re
import tempfile
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

# ========== CONFIGURATION ==========
TELEGRAM_BOT_TOKEN = "7966314098:AAEuW6yHTblcJXhG3AA915_geQtju4ck37c"  # Use your active token
COOKIES_FILE = 'cookies.txt'

# ========== LOGGING ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== GLOBAL STATE ==========
user_data = {}

# ========== COMMAND HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "YouTube Video Downloader Bot\n\n"
        "Send me any YouTube link and I'll download it for you!\n\n"
        "Supported:\n"
        "- Videos\n- Shorts\n- Playlists\n\n"
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
    
    # Create resolution selection keyboard
    keyboard = [
        [InlineKeyboardButton("360p", callback_data="360"),
         InlineKeyboardButton("480p", callback_data="480")],
        [InlineKeyboardButton("720p", callback_data="720"),
         InlineKeyboardButton("Best Available", callback_data="best")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Select video quality (higher qualities may not be available for all videos):",
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
        # Download the video
        file_path, title = download_youtube_video(url, resolution)
        
        # Upload to Telegram
        await query.message.reply_text("📤 Uploading to Telegram...")
        
        with open(file_path, 'rb') as video_file:
            await query.message.reply_video(
                video=video_file,
                caption=f"🎬 {title}\nQuality: {resolution}p",
                supports_streaming=True,
                read_timeout=300,
                write_timeout=300,
                connect_timeout=300
            )
        
        # Cleanup
        os.remove(file_path)
        
    except Exception as e:
        error_msg = str(e)
        if 'ffmpeg' in error_msg:
            error_msg = "This video format requires ffmpeg which is not available. Try a lower quality."
        elif 'cookies' in error_msg.lower() or 'sign in' in error_msg.lower():
            error_msg = "❌ This video requires login. I need cookies.txt file for age-restricted or private videos."
        
        await query.message.reply_text(f"❌ Error: {error_msg}")

def download_youtube_video(url, resolution):
    """Download YouTube video synchronously (no async issues)"""
    # Check if cookies file exists
    cookies_available = os.path.exists(COOKIES_FILE)
    logger.info(f"Cookies file available: {cookies_available}")
    
    # Format selection
    format_map = {
        '360': 'best[height<=360][ext=mp4]',
        '480': 'best[height<=480][ext=mp4]',
        '720': 'best[height<=720][ext=mp4]',
        'best': 'best[ext=mp4]'
    }
    
    ydl_opts = {
        'format': format_map.get(resolution, 'best[ext=mp4]'),
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),
        'quiet': False,
        'cookiefile': COOKIES_FILE if cookies_available else None,
        'logger': logger,
        'ignoreerrors': True,
        'no_warnings': False,
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            logger.info(f"Successfully downloaded: {file_path}")
            return file_path, info.get('title', 'YouTube Video')
            
    except Exception as e:
        logger.error(f"YouTube download failed: {str(e)}")
        raise Exception(f"Failed to download video: {str(e)}")

# ========== MAIN APPLICATION ==========
def main():
    """Start the Telegram bot"""
    print(f"🔧 Starting bot with token: {TELEGRAM_BOT_TOKEN[:15]}...")
    
    # 1. Create the bot application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # 2. Add all handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
    app.add_handler(CallbackQueryHandler(handle_resolution_selection))
    
    # 3. Check for required files
    if not os.path.exists(COOKIES_FILE):
        logger.warning(f"⚠️  {COOKIES_FILE} not found! Age-restricted videos may fail.")
    
    # 4. Start the bot
    logger.info("🤖 Bot is starting...")
    print("✅ Bot initialized. Send /start to your bot in Telegram!")
    
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == '__main__':
    main()
