import os
import logging
import re
import base64
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from yt_dlp import YoutubeDL
from functools import partial
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
CLIENT_SECRET_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'
COOKIES_FILE = 'cookies.txt'
DOWNLOAD_DIR = 'downloads'

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create credentials.json from environment variable
if GOOGLE_CREDENTIALS and not os.path.exists(CLIENT_SECRET_FILE):
    try:
        decoded_creds = base64.b64decode(GOOGLE_CREDENTIALS).decode()
        with open(CLIENT_SECRET_FILE, 'w') as f:
            f.write(decoded_creds)
    except Exception as e:
        logger.error(f"Failed to create credentials.json: {e}")
        raise

# Create cookies.txt from environment variable
YOUTUBE_COOKIES = os.getenv('YOUTUBE_COOKIES')
if YOUTUBE_COOKIES and not os.path.exists(COOKIES_FILE):
    try:
        decoded_cookies = base64.b64decode(YOUTUBE_COOKIES)
        with open(COOKIES_FILE, 'wb') as f:
            f.write(decoded_cookies)
    except Exception as e:
        logger.error(f"Failed to create cookies.txt: {e}")
        raise

def authorize_google_drive():
    """Authorize Google Drive API using credentials.json"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return creds

def progress_hook(d, update: Update, loop: asyncio.AbstractEventLoop):
    """Progress hook for yt-dlp (synchronous)"""
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        message = f"⬇️ Downloading...\nProgress: {percent}\nSpeed: {speed}\nETA: {eta}"
        
        # Schedule the async message send in the main event loop
        asyncio.run_coroutine_threadsafe(
            update.message.reply_text(message),
            loop
        )

async def download_youtube_video(url: str, update: Update):
    """Download YouTube video in a thread"""
    loop = asyncio.get_event_loop()
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'cookiefile': COOKIES_FILE,
        'quiet': True,
        'progress_hooks': [partial(progress_hook, update=update, loop=loop)],
    }
    
    # Run synchronous download in a thread
    return await asyncio.to_thread(_download_sync, url, ydl_opts)

def _download_sync(url: str, ydl_opts: dict):
    """Synchronous download logic"""
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        duration = info.get('duration', 0)
        size = os.path.getsize(file_path)
        title = info.get('title', 'Unknown Title')
        
        # Handle thumbnail
        thumbnail_path = os.path.join(DOWNLOAD_DIR, 'thumbnail.jpg')
        thumbnail_url = info.get('thumbnail', '')
        if thumbnail_url:
            # Use yt-dlp to download thumbnail directly
            ydl.params.update({'writethumbnail': True})
            ydl.download_thumbnail(info)
            thumbnail_ext = info.get('thumbnail_extension', 'jpg')
            os.rename(
                os.path.join(DOWNLOAD_DIR, f"{info['id']}.{thumbnail_ext}"),
                thumbnail_path
            )
            
        return file_path, title, duration, size, thumbnail_path

async def upload_to_google_drive(file_path: str, file_name: str, update: Update):
    """Upload file to Google Drive with progress updates"""
    try:
        creds = authorize_google_drive()
        if not creds or not creds.valid:
            return None

        service = build('drive', 'v3', credentials=creds)
        file_metadata = {'name': file_name}
        media = MediaFileUpload(file_path, resumable=True)
        
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                await update.message.reply_text(f"⬆️ Uploading...\nProgress: {progress}%")
        
        return response.get('id')
    except HttpError as e:
        logger.error(f"Google Drive API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return None

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube links sent by users"""
    try:
        url = update.message.text
        if not re.match(r'^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+', url):
            await update.message.reply_text("⚠️ Please send a valid YouTube URL.")
            return

        # Start download process
        await update.message.reply_text("⬇️ Downloading video...")
        file_path, title, duration, size, thumbnail_path = await download_youtube_video(url, update)

        # Verify downloaded file
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Downloaded file not found: {file_path}")

        # Send video details
        duration_min = duration // 60
        size_mb = size / (1024 * 1024)
        details_message = (
            f"📄 <b>Title:</b> {title}\n"
            f"⏱ <b>Duration:</b> {duration_min} minutes\n"
            f"📦 <b>Size:</b> {size_mb:.2f} MB\n"
        )
        await update.message.reply_text(details_message, parse_mode='HTML')

        # Send thumbnail if available
        if os.path.exists(thumbnail_path):
            try:
                with open(thumbnail_path, 'rb') as thumb:
                    await update.message.reply_photo(photo=thumb)
                os.remove(thumbnail_path)
            except Exception as e:
                logger.error(f"Failed to send thumbnail: {e}")

        # Start upload process
        await update.message.reply_text("⬆️ Uploading to Google Drive...")
        file_id = await upload_to_google_drive(file_path, f"{title}.mp4", update)

        # Cleanup and final message
        os.remove(file_path)
        if file_id:
            await update.message.reply_text(f"✅ Upload complete! File ID: {file_id}")
        else:
            await update.message.reply_text("❌ Failed to upload to Google Drive.")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Error in handle_youtube_link: {e}", exc_info=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.message.from_user
    welcome_message = (
        f"<b>Hi {user.first_name}, Welcome to YouTube to Drive Bot!</b>\n\n"
        "<blockquote>"
        "I can download YouTube videos and upload them to your Google Drive. "
        "Just send me a YouTube video link!"
        "</blockquote>"
    )
    await update.message.reply_text(welcome_message, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages"""
    user_message = update.message.text
    if re.match(r'^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+', user_message):
        await handle_youtube_link(update, context)
    else:
        await update.message.reply_text("⚠️ Please send a valid YouTube URL.")

def main():
    """Start the bot"""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == '__main__':
    main()
