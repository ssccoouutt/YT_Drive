import os
import yt_dlp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.error import TelegramError

# API Token for the bot (obtained from environment variable)
API_TOKEN = os.environ.get('API_TOKEN')  # Fetch API_TOKEN from environment variable

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

# Function to handle the /start command
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text('Send a YouTube link to download the video in the best quality.')

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

            # Check the file size
            file_size_mb = os.path.getsize(video_filename) / (1024 * 1024)
            if file_size_mb > 50:
                await message.edit_text('The video exceeds 50 MB and cannot be sent.')
                return

            # Send the video file to the user
            await message.edit_text('Sending the video...')
            try:
                await update.message.reply_video(video=open(video_filename, 'rb'))
            except TelegramError as e:
                await message.edit_text(f'Error sending the file: {e}')
                print(f"Error sending the file: {e}")
            finally:
                # Delete the downloaded file (optional)
                if os.path.exists(video_filename):
                    os.remove(video_filename)
        else:
            await update.message.reply_text('Please provide a valid YouTube URL.')

    except Exception as e:
        await update.message.reply_text('An unexpected error occurred. Please try again later.')
        print(f"Error in the download function: {e}")

# Main function to run the bot
def main():
    # Create the bot using ApplicationBuilder
    application = ApplicationBuilder().token(API_TOKEN).build()

    # Handled commands
    application.add_handler(CommandHandler('start', start))

    # Handle YouTube links directly
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
