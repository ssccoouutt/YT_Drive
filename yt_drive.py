import os
import logging
import re
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
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',  # Best quality MP4
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),
        'quiet': True,  # Suppress output
        'retries': 10,  # Retry up to 10 times
        'cookiefile': COOKIES_FILE if os.path.exists(COOKIES_FILE) else None,  # Use cookies.txt if available
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            file_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
            logger.info(f"Downloaded video: {file_path} ({file_size:.2f} MB)")
            return file_path, info['title']
    except Exception as e:
        logger.error(f"Failed to download YouTube video: {e}")
        raise

async def upload_to_google_drive(file_path, file_name):
    """Upload file to Google Drive."""
    creds = authorize_google_drive()
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube links."""
    url = update.message.text

    try:
        # Check if Google Drive is authorized
        creds = authorize_google_drive()
    except Exception as e:
        # If not authorized, start the OAuth2 flow
        await start_authorization(update, context)
        return

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

async def start_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the OAuth2 authorization flow."""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    context.user_data['flow'] = flow  # Store the flow object in user_data
    await update.message.reply_text(
        f"🔑 Authorization required!\n\n"
        f"Please visit this link to authorize:\n{auth_url}\n\n"
        "After authorization, send the code you receive back here."
    )

async def handle_authorization_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the authorization code from the user."""
    code = update.message.text.strip()
    flow = context.user_data.get('flow')
    if not flow:
        await update.message.reply_text("❌ No active authorization session. Please send a link first.")
        return

    try:
        flow.fetch_token(code=code)
        with open(TOKEN_FILE, 'w') as token_file:
            token_file.write(flow.credentials.to_json())
        await update.message.reply_text("✅ Authorization successful! You can now send links.")
    except Exception as e:
        await update.message.reply_text(f"❌ Authorization failed. Please try again. Error: {str(e)}")
        logger.error(f"Authorization error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all incoming messages."""
    message_text = update.message.text.strip()

    # Check if the message is an authorization code
    if re.match(r'^[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+$', message_text):
        await handle_authorization_code(update, context)
    # Check if the message is a YouTube link
    elif re.match(r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+', message_text):
        await handle_youtube_link(update, context)
    # Check if the message is a direct download link
    elif message_text.startswith(("http://", "https://")):
        await handle_direct_download_link(update, context)
    else:
        await update.message.reply_text("⚠️ Please send a valid YouTube URL, direct download link, or authorization code.")

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
