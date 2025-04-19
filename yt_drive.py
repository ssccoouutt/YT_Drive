import os
import logging
import re
import tempfile
import requests
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
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

# Authorization state
AUTH_STATE = 1
pending_authorizations = {}

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

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start Google Drive authorization process"""
    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_PATH,
        scopes=SCOPES,
        redirect_uri='http://localhost:8080'
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    pending_authorizations[update.effective_user.id] = flow
    
    await update.message.reply_text(
        "🔑 *Google Drive Authorization Required*\n\n"
        "1. Click this link to authorize:\n"
        f"[Authorize Google Drive]({auth_url})\n\n"
        "2. After approving, you'll see an error page (This is normal)\n"
        "3. Send me the complete URL from your browser's address bar\n\n"
        "⚠️ *Note:* You may see an 'unverified app' warning. Click 'Advanced' then 'Continue'",
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    return AUTH_STATE

async def handle_auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle received authorization code"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Extract code from URL
    code = None
    if 'code=' in text:
        code = text.split('code=')[1].split('&')[0]
    elif 'localhost' in text and '?code=' in text:
        code = text.split('?code=')[1].split('&')[0]
    
    if not code or user_id not in pending_authorizations:
        await update.message.reply_text("❌ Invalid authorization URL. Please try /auth again")
        return ConversationHandler.END
    
    try:
        flow = pending_authorizations[user_id]
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        with open(TOKEN_FILE, 'w') as token_file:
            token_file.write(creds.to_json())
        
        del pending_authorizations[user_id]
        await update.message.reply_text("✅ Authorization successful! Bot is now ready to use.")
    except Exception as e:
        await update.message.reply_text(f"❌ Authorization failed: {str(e)}")
    
    return ConversationHandler.END

async def cancel_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel authorization process"""
    user_id = update.effective_user.id
    if user_id in pending_authorizations:
        del pending_authorizations[user_id]
    
    await update.message.reply_text("❌ Authorization cancelled")
    return ConversationHandler.END

def get_drive_service():
    """Get authorized Drive service"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        else:
            raise Exception('Google Drive authorization required. Use /auth to authenticate.')
    
    return build('drive', 'v3', credentials=creds)

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
    service = get_drive_service()
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube links"""
    try:
        get_drive_service()  # Check auth first
    except Exception as e:
        await update.message.reply_text("🔑 Please authorize first using /auth")
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "Send me a YouTube link to upload to Google Drive!\n"
        "First, authorize with /auth"
    )

async def run_bot():
    """Main bot runner"""
    runner = await run_webserver()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add conversation handler for auth flow
    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("auth", auth_command)],
        states={
            AUTH_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_code)]
        },
        fallbacks=[CommandHandler("cancel", cancel_auth)]
    )
    
    app.add_handler(auth_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
    
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
