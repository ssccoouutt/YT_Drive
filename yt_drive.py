import os
import logging
import re
import tempfile
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler
)
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
COOKIES_FILE = 'cookies.txt'  # Make sure this is in your repository
PORT = 8000

# State
AUTH_STATE = 1
pending_flows = {}

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Web Server
async def health_check(request):
    return web.Response(text="🤖 Bot is running")

async def run_webserver():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Health check running on port {PORT}")
    return runner

# ====== WORKING AUTHORIZATION FLOW ======
async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri='http://localhost:8080'
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    pending_flows[update.effective_user.id] = flow
    
    await update.message.reply_text(
        "🔑 AUTHORIZATION STEPS:\n\n"
        "1. Click: " + auth_url + "\n"
        "2. Approve access\n"
        "3. Copy the LOCALHOST URL\n"
        "4. Send it back to me\n\n"
        "⚠️ Ignore browser errors after approving",
        disable_web_page_preview=True
    )
    return AUTH_STATE

async def handle_auth_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    
    if 'localhost' not in url or 'code=' not in url:
        await update.message.reply_text("❌ Send the EXACT localhost URL from your browser")
        return AUTH_STATE
    
    try:
        code = url.split('code=')[1].split('&')[0]
        flow = pending_flows[user_id]
        flow.fetch_token(code=code)
        
        with open(TOKEN_FILE, 'w') as token_file:
            token_file.write(flow.credentials.to_json())
        
        del pending_flows[user_id]
        await update.message.reply_text("✅ AUTHORIZATION SUCCESSFUL! Now send YouTube links")
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ FAILED: {str(e)}\nTry /auth again")
        return ConversationHandler.END

# ====== YOUTUBE DOWNLOAD WITH COOKIES ======
async def download_youtube_video(url):
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),
        'quiet': True,
        'cookiefile': COOKIES_FILE,
        'extract_flat': False,
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            return file_path, info['title']
    except Exception as e:
        logger.error(f"YouTube download failed: {str(e)}")
        raise Exception("Failed to download video. Make sure cookies.txt is valid.")

# ====== DRIVE UPLOAD ======
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception('Use /auth first')
    return build('drive', 'v3', credentials=creds)

async def upload_to_drive(file_path, file_name):
    service = get_drive_service()
    media = MediaFileUpload(file_path)
    file = service.files().create(
        body={'name': file_name},
        media_body=media,
        fields='id'
    ).execute()
    return file.get('id')

# ====== MESSAGE HANDLERS ======
async def handle_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    try:
        # Check Drive auth first
        get_drive_service()
        
        await update.message.reply_text("⬇️ Downloading video...")
        file_path, title = await download_youtube_video(url)
        
        await update.message.reply_text("⬆️ Uploading to Drive...")
        file_id = await upload_to_drive(file_path, f"{title}.mp4")
        
        await update.message.reply_text(f"✅ Uploaded! File ID: {file_id}")
        os.remove(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if re.match(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+', text):
        await handle_youtube(update, context)
    else:
        await update.message.reply_text("Send YouTube links or /auth")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send YouTube links to upload to Google Drive\n"
        "First run /auth to authorize"
    )

# ====== MAIN APP ======
async def run_bot():
    runner = await run_webserver()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Auth conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("auth", auth_command)],
        states={
            AUTH_STATE: [MessageHandler(filters.TEXT, handle_auth_url)]
        },
        fallbacks=[]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Bot is running and ready")
    
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    # Verify cookies file exists
    if not os.path.exists(COOKIES_FILE):
        logger.error("❌ cookies.txt not found! Download will fail without it")
    
    asyncio.run(run_bot())
