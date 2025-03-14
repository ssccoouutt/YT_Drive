import os
import re  # Add this import
import logging
import tempfile
import base64
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
CLIENT_SECRET_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'
COOKIES_FILE = 'cookies.txt'  # Add cookies.txt support

# Initialize logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Create credentials.json from environment variable
if GOOGLE_CREDENTIALS and not os.path.exists(CLIENT_SECRET_FILE):
    with open(CLIENT_SECRET_FILE, 'w') as f:
        f.write(base64.b64decode(GOOGLE_CREDENTIALS).decode())

def authorize_google_drive():
    """Authorize Google Drive API using OAuth2."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("Google Drive authorization required.")
    return creds

async def download_youtube_video(url):
    """Download YouTube video using yt-dlp with cookies support."""
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),
        'quiet': True,
    }

    # Add cookies.txt if it exists
    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE
        logger.info("Using cookies.txt for YouTube download")
    else:
        logger.warning("cookies.txt not found. Proceeding without cookies.")

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            return file_path, info['title']
    except Exception as e:
        logger.error(f"YouTube download failed: {e}")
        raise

async def upload_to_google_drive(file_path, file_name):
    """Upload file to Google Drive."""
    creds = authorize_google_drive()
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id,webViewLink').execute()
    return file.get('webViewLink')

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube link processing."""
    try:
        # Download video
        await update.message.reply_text("🚀 Downloading video...")
        file_path, title = await download_youtube_video(update.message.text)
        
        # Upload to Google Drive
        await update.message.reply_text("☁️ Uploading to Google Drive...")
        drive_link = await upload_to_google_drive(file_path, f"{title}.mp4")
        
        # Send confirmation
        await update.message.reply_text(f"✅ Uploaded! 🔗 {drive_link}")
        
        # Cleanup
        os.remove(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text("Send a YouTube link to upload it to Google Drive.")

def main():
    """Start the bot."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
    app.run_polling()

if __name__ == '__main__':
    main()
