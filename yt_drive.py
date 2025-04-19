import os
import logging
import re
import tempfile
import requests
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from yt_dlp import YoutubeDL
from aiohttp import web

# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive']
TELEGRAM_BOT_TOKEN = "8080486871:AAECgE7E8cbkrBqFQdqLdtz89-7-v17u6qI"
CLIENT_SECRET_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'
COOKIES_FILE = 'cookies.txt'
PORT = 8000

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def health_check(request):
    return web.Response(text="🤖 Bot is running")

async def run_webserver():
    """Run health check server for Koyeb"""
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Health check server running on port {PORT}")
    return runner

def authorize_google_drive():
    """Authorize Google Drive API"""
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
    """Download YouTube video"""
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),
        'quiet': True,
    }
    
    if os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
    return file_path, info['title']

async def upload_to_google_drive(file_path, file_name):
    """Upload file to Google Drive"""
    creds = authorize_google_drive()
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

async def start_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start OAuth2 flow"""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    context.user_data['flow'] = flow
    await update.message.reply_text(
        f"🔑 Authorization required!\n\n"
        f"Please visit this link to authorize:\n{auth_url}\n\n"
        "After authorization, send the code you receive back here."
    )

async def handle_authorization_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle authorization code"""
    code = update.message.text.strip()
    flow = context.user_data.get('flow')
    if not flow:
        await update.message.reply_text("❌ No active authorization session")
        return

    try:
        flow.fetch_token(code=code)
        with open(TOKEN_FILE, 'w') as token_file:
            token_file.write(flow.credentials.to_json())
        await update.message.reply_text("✅ Authorization successful!")
    except Exception as e:
        await update.message.reply_text(f"❌ Authorization failed: {str(e)}")

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube links"""
    try:
        authorize_google_drive()  # Check auth first
    except Exception:
        await start_authorization(update, context)
        return

    url = update.message.text
    try:
        await update.message.reply_text("⬇️ Downloading video...")
        file_path, title = await download_youtube_video(url)
        
        await update.message.reply_text("⬆️ Uploading to Google Drive...")
        drive_file_id = await upload_to_google_drive(file_path, f"{title}.mp4")
        
        await update.message.reply_text(f"✅ Uploaded to Google Drive! ID: {drive_file_id}")
        os.remove(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages"""
    text = update.message.text.strip()
    
    if re.match(r'^[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+$', text):
        await handle_authorization_code(update, context)
    elif re.match(r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+', text):
        await handle_youtube_link(update, context)
    elif text.startswith(("http://", "https://")):
        await handle_direct_download_link(update, context)
    else:
        await update.message.reply_text("⚠️ Please send a YouTube URL or direct download link")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "Send me a YouTube link or direct download link to upload to Google Drive!"
    )

async def run_bot():
    """Main bot runner"""
    runner = await run_webserver()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await app.initialize()
    await app.start()
    logger.info("🤖 Bot is running with polling...")
    
    # Start polling explicitly
    await app.updater.start_polling()
    
    # Keep running
    while True:
        await asyncio.sleep(3600)

async def main():
    """Entry point"""
    try:
        await run_bot()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        loop.close()
