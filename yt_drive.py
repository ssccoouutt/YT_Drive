import os
import yt_dlp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.error import TelegramError
import base64
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Telegram Bot Token (obtained from environment variable)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')  # Fetch TELEGRAM_BOT_TOKEN from environment variable
GOOGLE_CREDENTIALS = os.environ.get('GOOGLE_CREDENTIALS')  # Fetch base64-encoded Google Credentials from environment variable

# Google Drive API Scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Function to download YouTube videos
def download_video(url, destination_folder):
    try:
        # yt-dlp configuration
        options = {
            'outtmpl': f'{destination_folder}/%(id)s.%(ext)s',  # Use the video ID to avoid filename issues
            'format': 'best',  # Select the best quality format
            'restrictfilenames': True,  # Limit special characters
        }

        # Download the video
        with yt_dlp.YoutubeDL(options) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info_dict)
        return filename
    except Exception as e:
        print(f"Error during download: {e}")
        return None

# Function to handle Google Drive authorization
def authorize_google_drive(update: Update, context: CallbackContext):
    try:
        # Decode the base64-encoded Google Credentials
        creds_json = base64.b64decode(GOOGLE_CREDENTIALS).decode('utf-8')
        creds_dict = json.loads(creds_json)

        # Load or create credentials
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_config(creds_dict, SCOPES)
                auth_url, _ = flow.authorization_url(prompt='consent')
                await update.message.reply_text(f'Please authorize the bot by visiting this URL: {auth_url}')
                context.user_data['flow'] = flow
                return None
            # Save the credentials to token.json
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return creds
    except Exception as e:
        print(f"Error during Google Drive authorization: {e}")
        return None

# Function to upload file to Google Drive
def upload_to_google_drive(creds, file_path, file_name):
    try:
        service = build('drive', 'v3', credentials=creds)
        file_metadata = {'name': file_name}
        media = MediaFileUpload(file_path, mimetype='video/mp4')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        print(f"Error uploading to Google Drive: {e}")
        return None

# Function to handle the /start command
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text('Send a YouTube link to download the video and upload it to Google Drive.')

# Function to handle YouTube video links
async def handle_youtube_link(update: Update, context: CallbackContext):
    try:
        # Extract the text sent after the command
        message_text = update.message.text

        # Check if the message contains a valid YouTube URL
        if "https://www.youtube.com/" in message_text or "https://youtu.be/" in message_text:
            url = message_text  # Extract the URL from the message
            destination_folder = os.getenv('TEMP', '/tmp')  # Use the default temporary directory

            # Notify the user that the download is starting
            message = await update.message.reply_text('Starting the video download...')

            # Download the video
            video_filename = download_video(url, destination_folder)

            if not video_filename:
                await message.edit_text('Error during the video download. Please try again later.')
                return

            # Authorize Google Drive
            creds = authorize_google_drive(update, context)
            if not creds:
                return  # Authorization is in progress

            # Upload the video to Google Drive
            await message.edit_text('Uploading the video to Google Drive...')
            file_id = upload_to_google_drive(creds, video_filename, os.path.basename(video_filename))

            if file_id:
                await message.edit_text(f'Video uploaded to Google Drive with file ID: {file_id}')
            else:
                await message.edit_text('Error uploading the video to Google Drive.')

            # Delete the downloaded file (optional)
            if os.path.exists(video_filename):
                os.remove(video_filename)
        else:
            await update.message.reply_text('Please provide a valid YouTube URL.')

    except Exception as e:
        await update.message.reply_text('An unexpected error occurred. Please try again later.')
        print(f"Error in the download function: {e}")

# Function to handle authorization code
async def handle_authorization_code(update: Update, context: CallbackContext):
    try:
        authorization_code = update.message.text
        flow = context.user_data.get('flow')
        if flow:
            flow.fetch_token(code=authorization_code)
            creds = flow.credentials
            # Save the credentials to token.json
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
            await update.message.reply_text('Authorization successful! You can now send YouTube links.')
            context.user_data['flow'] = None
        else:
            await update.message.reply_text('No pending authorization. Please send a YouTube link.')
    except Exception as e:
        await update.message.reply_text('Error during authorization. Please try again.')
        print(f"Error in authorization: {e}")

# Main function to run the bot
def main():
    # Create the bot using ApplicationBuilder
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Handled commands
    application.add_handler(CommandHandler('start', start))

    # Handle YouTube links directly
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))

    # Handle authorization codes
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_authorization_code))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
