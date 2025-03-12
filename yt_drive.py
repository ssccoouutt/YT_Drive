import os
import logging
import re
import tempfile
import json
import base64
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from yt_dlp import YoutubeDL

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Google Drive API Scopes
SCOPES = ['https://www.googleapis.com/auth/drive']

# Load environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_CREDENTIALS_BASE64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")  # Base64-encoded credentials
COOKIES_FILE = "cookies.txt"  # Assuming cookies.txt is in the root directory

def authorize_google_drive():
    """Authorize Google Drive API using credentials from base64-encoded environment variable"""
    creds = None
    if GOOGLE_CREDENTIALS_BASE64:
        # Decode the base64-encoded credentials
        creds_json = base64.b64decode(GOOGLE_CREDENTIALS_BASE64).decode('utf-8')
        creds_data = json.loads(creds_json)
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return creds

async def download_youtube_video(url):
    """Download YouTube video using yt-dlp"""
    ydl_opts = {
        'format': 'best',  # Download the best quality available
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),  # Save to temp directory
        'cookiefile': COOKIES_FILE,  # Use cookies.txt for age-restricted videos
        'quiet': True,  # Suppress yt-dlp output
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
    return file_path, info['title']

async def upload_to_google_drive(file_path, file_name):
    """Upload file to Google Drive"""
    creds = authorize_google_drive()
    if not creds or not creds.valid:
        return None

    service = build('drive', 'v3', credentials=creds)
    file_metadata = {
        'name': file_name,
        'mimeType': 'video/mp4',
    }
    media = MediaFileUpload(file_path, mimetype='video/mp4')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube links sent by users"""
    try:
        url = update.message.text
        if not re.match(r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+', url):
            await update.message.reply_text("⚠️ Please send a valid YouTube URL.")
            return

        await update.message.reply_text("⬇️ Downloading video...")
        file_path, title = await download_youtube_video(url)

        await update.message.reply_text("⬆️ Uploading to Google Drive...")
        file_id = await upload_to_google_drive(file_path, f"{title}.mp4")

        if file_id:
            await update.message.reply_text(f"✅ Upload complete! File ID: {file_id}")
        else:
            await update.message.reply_text("❌ Failed to upload to Google Drive.")

        # Clean up downloaded file
        os.remove(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Error in handle_youtube_link: {e}")

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
    
    await update.message.reply_text(
        welcome_message,
        parse_mode='HTML'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages"""
    user_message = update.message.text
    if re.match(r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+', user_message):
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
