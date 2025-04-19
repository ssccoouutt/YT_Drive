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
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from yt_dlp import YoutubeDL
from aiohttp import web

# ========== CONFIGURATION ==========
SCOPES = ['https://www.googleapis.com/auth/drive']
TELEGRAM_BOT_TOKEN = "8080486871:AAECgE7E8cbkrBqFQdqLdtz89-7-v17u6qI"
CLIENT_SECRET_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'
COOKIES_FILE = 'cookies.txt'
PORT = 8000

# ========== AUTHORIZATION STATE ==========
AUTH_STATE = 1
pending_authorizations = {}

# ========== LOGGING SETUP ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== WEB SERVER FOR KOYEB ==========
async def health_check(request):
    return web.Response(text="🤖 Bot is running")

async def run_webserver():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Health check server running on port {PORT}")
    return runner

# ========== GOOGLE DRIVE AUTHENTICATION ==========
async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the OAuth2 flow using the working method"""
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            CLIENT_SECRET_FILE,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # Critical change that fixes the error
        )
        auth_url, _ = flow.authorization_url(prompt='consent')
        pending_authorizations[update.effective_user.id] = flow
        
        await update.message.reply_text(
            "🔑 *Google Drive Authorization*\n\n"
            "1. Click this link:\n"
            f"{auth_url}\n\n"
            "2. Approve access\n"
            "3. You'll get a CODE (not URL)\n"
            "4. Send me that code\n\n"
            "⚠️ If you see a warning, click 'Advanced' then 'Continue'",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        return AUTH_STATE
    except Exception as e:
        await update.message.reply_text(f"❌ Authorization failed to start: {e}")
        return ConversationHandler.END

async def handle_auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the authorization code"""
    user_id = update.effective_user.id
    auth_code = update.message.text.strip()
    
    if not auth_code or len(auth_code) < 20 or '/' in auth_code:
        await update.message.reply_text("❌ Please send only the code (no URLs)")
        return AUTH_STATE
    
    try:
        if user_id not in pending_authorizations:
            raise ValueError("No active authorization session")
            
        flow = pending_authorizations[user_id]
        flow.fetch_token(code=auth_code)
        creds = flow.credentials
        
        with open(TOKEN_FILE, 'w') as token_file:
            token_file.write(creds.to_json())
        
        del pending_authorizations[user_id]
        await update.message.reply_text("✅ Authorization successful! Now send YouTube links.")
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}\nTry /auth again")
        return ConversationHandler.END

async def cancel_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the authorization process"""
    user_id = update.effective_user.id
    if user_id in pending_authorizations:
        del pending_authorizations[user_id]
    await update.message.reply_text("❌ Authorization cancelled")
    return ConversationHandler.END

def get_drive_service():
    """Get authenticated Drive service"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        else:
            raise Exception('Authorization required. Use /auth')
    return build('drive', 'v3', credentials=creds)

# ========== YOUTUBE DOWNLOAD ==========
async def download_youtube_video(url):
    """Download video using yt-dlp"""
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

# ========== GOOGLE DRIVE UPLOAD ==========
async def upload_to_google_drive(file_path, file_name):
    """Upload file to Google Drive"""
    service = get_drive_service()
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    return file.get('id')

# ========== MESSAGE HANDLERS ==========
async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process YouTube links"""
    try:
        get_drive_service()  # Verify auth first
    except Exception:
        await update.message.reply_text("🔑 Please /auth first")
        return

    url = update.message.text
    try:
        await update.message.reply_text("⬇️ Downloading...")
        file_path, title = await download_youtube_video(url)
        
        await update.message.reply_text("⬆️ Uploading to Drive...")
        drive_id = await upload_to_google_drive(file_path, f"{title}.mp4")
        
        await update.message.reply_text(f"✅ Uploaded! Drive ID: {drive_id}")
        os.remove(file_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route incoming messages"""
    text = update.message.text.strip()
    
    if re.match(r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+', text):
        await handle_youtube_link(update, context)
    else:
        await update.message.reply_text("Send a YouTube link or /auth")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message"""
    await update.message.reply_text(
        "Welcome to YouTube Drive Uploader!\n\n"
        "1. First /auth\n"
        "2. Then send YouTube links"
    )

# ========== MAIN BOT SETUP ==========
async def run_bot():
    """Start the bot and web server"""
    runner = await run_webserver()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Authorization conversation handler
    auth_handler = ConversationHandler(
        entry_points=[CommandHandler("auth", auth_command)],
        states={
            AUTH_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth_code)]
        },
        fallbacks=[CommandHandler("cancel", cancel_auth)]
    )
    
    app.add_handler(auth_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await app.initialize()
    await app.start()
    logger.info("🤖 Bot is running...")
    await app.updater.start_polling()
    
    # Keep running
    while True:
        await asyncio.sleep(3600)

# ========== ENTRY POINT ==========
async def main():
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
