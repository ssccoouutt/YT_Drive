import os
import logging
import re
import base64
import uuid
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
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

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create credentials.json from environment variable
if GOOGLE_CREDENTIALS and not os.path.exists(CLIENT_SECRET_FILE):
    try:
        with open(CLIENT_SECRET_FILE, 'w') as f:
            f.write(base64.b64decode(GOOGLE_CREDENTIALS).decode())
    except Exception as e:
        logger.error(f"Failed to create credentials.json: {e}")
        raise

# Create cookies.txt from environment variable
YOUTUBE_COOKIES = os.getenv('YOUTUBE_COOKIES')
if YOUTUBE_COOKIES and not os.path.exists(COOKIES_FILE):
    try:
        with open(COOKIES_FILE, 'wb') as f:
            f.write(base64.b64decode(YOUTUBE_COOKIES))
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

async def download_youtube_video(url, update: Update):
    """Download YouTube video using yt-dlp with random filenames"""
    # Create downloads directory if not exists
    os.makedirs('downloads', exist_ok=True)
    
    # Generate unique identifiers
    unique_id = str(uuid.uuid4())
    base_path = os.path.join('downloads', unique_id)
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': f'{base_path}.%(ext)s',
        'cookiefile': COOKIES_FILE,
        'quiet': True,
        'progress_hooks': [partial(progress_hook, update=update)],
        'writethumbnail': True,  # Ensure thumbnail is downloaded
        'postprocessors': [{
            'key': 'FFmpegThumbnailsConvertor',
            'format': 'jpg',
        }],
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        duration = info.get('duration', 0)
        size = os.path.getsize(file_path)
        title = info.get('title', 'Unknown Title')
        
        # Thumbnail path (yt-dlp adds .webp by default, we convert to jpg)
        thumbnail_path = f'{base_path}.jpg'
        
    return file_path, title, duration, size, thumbnail_path

def progress_hook(d, update: Update):
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%')
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        message = f"⬇️ Downloading...\nProgress: {percent}\nSpeed: {speed}\nETA: {eta}"
        update.message.reply_text(message)

async def upload_to_google_drive(file_path, original_title, update: Update):
    """Upload file to Google Drive with random filename"""
    creds = authorize_google_drive()
    if not creds or not creds.valid:
        return None

    service = build('drive', 'v3', credentials=creds)
    file_name = f"{original_title[:50]} - {str(uuid.uuid4())[:8]}.mp4"
    
    file_metadata = {
        'name': file_name,
        'mimeType': 'video/mp4',
    }
    
    media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
    request = service.files().create(body=file_metadata, media_body=media, fields='id')
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            await update.message.reply_text(f"⬆️ Uploading...\nProgress: {progress}%")
    return response.get('id')

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        url = update.message.text
        if not re.match(r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+', url):
            await update.message.reply_text("⚠️ Please send a valid YouTube URL.")
            return

        await update.message.reply_text("⬇️ Downloading video...")
        file_path, title, duration, size, thumbnail_path = await download_youtube_video(url, update)

        # Send video details
        duration_min = duration // 60
        size_mb = size / (1024 * 1024)
        details_message = (
            f"📄 <b>Title:</b> {title}\n"
            f"⏱ <b>Duration:</b> {duration_min} minutes\n"
            f"📦 <b>Size:</b> {size_mb:.2f} MB\n"
        )
        await update.message.reply_text(details_message, parse_mode='HTML')

        # Send thumbnail
        if os.path.exists(thumbnail_path):
            with open(thumbnail_path, 'rb') as thumb:
                await update.message.reply_photo(photo=thumb)
            os.remove(thumbnail_path)

        await update.message.reply_text("⬆️ Uploading to Google Drive...")
        file_id = await upload_to_google_drive(file_path, title, update)

        if file_id:
            await update.message.reply_text(f"✅ Upload complete! File ID: {file_id}")
        else:
            await update.message.reply_text("❌ Failed to upload to Google Drive.")

        # Clean up files
        os.remove(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Error in handle_youtube_link: {e}")

# ... keep the rest of the code (start, handle_message, main) the same ...
