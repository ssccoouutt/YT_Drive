import os
import logging
import requests
import base64
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # From Railway environment
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')  # Base64 encoded credentials
CLIENT_SECRET_FILE = 'credentials.json'  # Will be created from environment variable
TOKEN_FILE = 'token.json'  # Will be stored in Railway's ephemeral storage

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

def upload_to_google_drive(file_path, file_name):
    """Upload a file to Google Drive."""
    creds = authorize_google_drive()
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {'name': file_name}
    media = MediaFileUpload(file_path, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

def start(update: Update, context: CallbackContext) -> None:
    """Handler for the /start command."""
    update.message.reply_text("Send me a direct download link, and I'll upload it to your Google Drive!")

def handle_authorization_code(update: Update, context: CallbackContext) -> None:
    """Handle the authorization code from the user."""
    code = update.message.text.strip()
    try:
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRET_FILE,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        flow.fetch_token(code=code)
        with open(TOKEN_FILE, 'w') as token_file:
            token_file.write(flow.credentials.to_json())
        update.message.reply_text("✅ Authorization successful! You can now send direct download links.")
    except Exception as e:
        update.message.reply_text(f"❌ Authorization failed. Please try again. Error: {str(e)}")
        logger.error(f"Authorization error: {e}")

def handle_document_link(update: Update, context: CallbackContext) -> None:
    """Handler for direct download links."""
    url = update.message.text

    # Validate the URL
    if not url.startswith(("http://", "https://")):
        update.message.reply_text("Please send a valid direct download link.")
        return

    try:
        # Check if Google Drive is authorized
        creds = authorize_google_drive()
    except Exception as e:
        # If not authorized, start the OAuth2 flow
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRET_FILE,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        auth_url, _ = flow.authorization_url(prompt='consent')
        update.message.reply_text(
            f"🔑 Authorization required!\n\n"
            f"Please visit this link to authorize:\n{auth_url}\n\n"
            "After authorization, send the code you receive back here."
        )
        return

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
        drive_file_id = upload_to_google_drive(file_name, file_name)
        update.message.reply_text(f"✅ File uploaded to Google Drive with ID: {drive_file_id}")

        # Clean up the temporary file
        os.remove(file_name)

    except Exception as e:
        update.message.reply_text(f"❌ Failed to process the file. Error: {str(e)}")
        logger.error(f"File processing error: {e}")

def main() -> None:
    """Start the Telegram bot."""
    # Initialize the Telegram Bot
    updater = Updater(TELEGRAM_BOT_TOKEN)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Register command and message handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_document_link))

    # Start the Bot
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
