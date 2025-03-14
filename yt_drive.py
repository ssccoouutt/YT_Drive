import os
import re
import logging
import tempfile
import base64
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
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
    """Download YouTube video using yt-dlp."""
    temp_dir = tempfile.gettempdir()
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(temp_dir, '%(title)s [%(id)s].%(ext)s'),
        'quiet': True,
        'no_warnings': True,
    }

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
    try:
        creds = authorize_google_drive()
        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {'name': file_name}
        media = MediaFileUpload(file_path, resumable=True)
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,webViewLink'
        ).execute()
        
        return file.get('id'), file.get('webViewLink')
    except Exception as e:
        logger.error(f"Google Drive upload failed: {e}")
        raise

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube link processing."""
    url = update.message.text.strip()
    user = update.message.from_user

    try:
        # Check authorization first
        authorize_google_drive()
    except Exception as e:
        await start_authorization(update, context)
        return

    try:
        # Step 1: Download video
        await update.message.reply_text("🚀 Starting YouTube download...")
        file_path, title = await download_youtube_video(url)
        
        # Step 2: Upload to Google Drive
        await update.message.reply_text("☁️ Uploading to Google Drive...")
        drive_id, drive_link = await upload_to_google_drive(file_path, f"{title}.mp4")
        
        # Step 3: Send confirmation
        await update.message.reply_text(
            f"✅ Successfully uploaded!\n\n"
            f"📁 Title: {title}\n"
            f"🔗 Drive Link: {drive_link}"
        )
        
        # Cleanup
        os.remove(file_path)
        logger.info(f"Successfully processed video for {user.full_name} ({user.id})")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Processing failed for {user.full_name}: {str(e)}")
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)

# Keep other functions (start_authorization, handle_authorization_code, etc.) same as previous version
# ... [Rest of the code remains unchanged]
