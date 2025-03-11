import os
import logging
import base64
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pytube import YouTube
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # From environment
YOUTUBE_COOKIES = os.getenv('YOUTUBE_COOKIES')  # Base64 encoded cookies
CLIENT_SECRET_FILE = 'credentials.json'  # Google Drive credentials
TOKEN_FILE = 'token.json'  # Google Drive token

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def authorize_google_drive():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    return creds

async def upload_to_drive(file_path, file_name, creds):
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, mimetype='video/mp4')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

async def download_youtube_video(url, chat_id):
    cookies_file = f'cookies_{chat_id}.txt'
    with open(cookies_file, 'wb') as f:
        f.write(base64.b64decode(YOUTUBE_COOKIES))
    
    yt = YouTube(url)
    yt.bypass_age_gate()
    stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
    file_path = stream.download(output_path='downloads', filename=f'{chat_id}.mp4')
    return file_path, yt.title

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    url = update.message.text

    try:
        await update.message.reply_text("⏬ Downloading video from YouTube...")
        file_path, title = await download_youtube_video(url, chat_id)
        
        await update.message.reply_text("⏫ Uploading video to Google Drive...")
        creds = authorize_google_drive()
        if not creds or not creds.valid:
            await update.message.reply_text("🔑 Please authorize the bot to access Google Drive.")
            return
        
        file_id = await upload_to_drive(file_path, f"{title}.mp4", creds)
        await update.message.reply_text(f"✅ Video uploaded successfully! File ID: {file_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Error handling YouTube link: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Send me a YouTube link to upload it to Google Drive.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
    app.run_polling()

if __name__ == '__main__':
    main()