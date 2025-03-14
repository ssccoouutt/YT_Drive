import os
import logging
import re
import tempfile
import base64
import requests
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
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # From Railway environment
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')  # Base64 encoded credentials
CLIENT_SECRET_FILE = 'credentials.json'  # Created from environment variable
TOKEN_FILE = 'token.json'  # Stored in Railway's ephemeral storage
COOKIES_FILE = 'cookies.txt'  # Directly reference the file in the repository

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
    ydl_opts = {
        'format': 'best',  # Best quality
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),
        'quiet': True,  # Suppress output
    }
    
    # Add cookies.txt if it exists in the repository
    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE
        logger.info("Using cookies.txt for YouTube download")
    else:
        logger.warning("cookies.txt not found. Proceeding without cookies.")

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
    return file_path, info['title']

async def upload_to_google_drive(file_path, file_name):
    """Upload file to Google Drive."""
    creds = authorize_google_drive()
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

async def handle_direct_download_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct download links."""
    url = update.message.text

    try:
        # Download the file
        response = requests.get(url, stream=True)
        response.raise_for_status()

        # Get the file name from the URL or use a default name
        file_name = url.split("/")[-1] or "downloaded_file"

        # Save the file temporarily
        with open(file_name, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

        # Upload the file to Google Drive
        drive_file_id = await upload_to_google_drive(file_name, file_name)
        await update.message.reply_text(f"✅ File uploaded to Google Drive with ID: {drive_file_id}")

        # Clean up the temporary file
        os.remove(file_name)

    except Exception as e:
        await update.message.reply_text(f"❌ Failed to process the file. Error: {str(e)}")
        logger.error(f"Direct download error: {e}")

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube links."""
    url = update.message.text

    try:
        await update.message.reply_text("⬇️ Downloading YouTube video...")
        file_path, title = await download_youtube_video(url)

        await update.message.reply_text("⬆️ Uploading to Google Drive...")
        drive_file_id = await upload_to_google_drive(file_path, f"{title}.mp4")

        if drive_file_id:
            await update.message.reply_text(f"✅ YouTube video uploaded to Google Drive with ID: {drive_file_id}")
        else:
            await update.message.reply_text("❌ Failed to upload to Google Drive.")

        # Clean up downloaded file
        os.remove(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"YouTube download error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all incoming messages."""
    message_text = update.message.text.strip()

    # Check if the message is a YouTube link
    if re.match(r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+', message_text):
        await handle_youtube_link(update, context)
    # Check if the message is a direct download link
    elif message_text.startswith(("http://", "https://")):
        await handle_direct_download_link(update, context)
    else:
        await update.message.reply_text("⚠️ Please send a valid YouTube URL or direct download link.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Send me a direct download link or a YouTube video link, and I'll upload it to your Google Drive!"
    )

def main():
    """Start the bot."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == '__main__':
    main()
