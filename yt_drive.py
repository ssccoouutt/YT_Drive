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
    return web.Response(text="Bot is running")

async def run_webserver():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    return runner

# ====== WORKING AUTHORIZATION FLOW ======
async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """EXACT flow from your working example"""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri='http://localhost:8080'  # THIS IS CRUCIAL
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    pending_flows[update.effective_user.id] = flow
    
    await update.message.reply_text(
        "🔑 AUTHORIZATION STEPS:\n\n"
        "1. Click this link:\n"
        f"{auth_url}\n\n"
        "2. Approve access\n"
        "3. You'll get a LOCALHOST URL\n"
        "4. Send me that ENTIRE URL\n\n"
        "⚠️ Ignore browser errors after approval",
        disable_web_page_preview=True
    )
    return AUTH_STATE

async def handle_auth_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the localhost URL"""
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
        await update.message.reply_text("✅ AUTHORIZATION SUCCESSFUL!")
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ FAILED: {str(e)}\nTry /auth again")
        return ConversationHandler.END

# ====== CORE FUNCTIONALITY ======
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

async def download_upload(update: Update, url: str):
    """Download and upload workflow"""
    try:
        # Download
        with YoutubeDL({
            'format': 'best',
            'outtmpl': os.path.join(tempfile.gettempdir(), '%(title)s.%(ext)s'),
            'quiet': True
        }) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
        
        # Upload
        service = get_drive_service()
        media = MediaFileUpload(file_path)
        file = service.files().create(
            body={'name': info['title'] + '.mp4'},
            media_body=media,
            fields='id'
        ).execute()
        
        await update.message.reply_text(f"✅ Uploaded! File ID: {file.get('id')}")
        os.remove(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ====== MESSAGE HANDLERS ======
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if re.match(r'https?://(www\.)?(youtube\.com|youtu\.be)/.+', text):
        try:
            get_drive_service()
            await download_upload(update, text)
        except Exception:
            await update.message.reply_text("🔑 First /auth to authorize Google Drive")
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
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(run_bot())
