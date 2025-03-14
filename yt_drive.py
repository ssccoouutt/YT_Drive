import os
import yt_dlp
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackContext
from telegram.error import TelegramError

# API Token for the bot (obtained from environment variable)
API_TOKEN = os.environ.get('API_TOKEN')  # Fetch API_TOKEN from environment variable

# Function to handle real-time download progress
async def download_progress(d, message):
    if d['status'] == 'downloading':
        percentage = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
        # Update the progress by editing the same message
        if int(percentage) % 10 == 0:  # Update every 10% to avoid too many edits
            await message.edit_text(f"Download progress: {percentage:.2f}%")
    elif d['status'] == 'finished':
        await message.edit_text("Download complete, processing file...")

# Function to download YouTube videos
async def download_video(url, destination_folder, message):
    try:
        # yt-dlp configuration with progress_hooks
        options = {
            'outtmpl': f'{destination_folder}/%(id)s.%(ext)s',  # Use the video ID to avoid filename issues
            'format': 'best',  # Select the best quality format
            'restrictfilenames': True,  # Limit special characters
            'progress_hooks': [lambda d: asyncio.create_task(download_progress(d, message))],  # Hook to show real-time progress
        }

        # Download the video
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        print(f"Error during download: {e}")
        return False

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

            # Send the initial message and keep it for updates
            message = await update.message.reply_text(f'Starting the video download from: {url}')

            # Start the download and update the same message
            success_download = await download_video(url, destination_folder, message)

            if not success_download:
                await message.edit_text('Error during the video download. Please try again later.')
                return

            # Get the name of the downloaded file
            video_filename = max([os.path.join(destination_folder, f) for f in os.listdir(destination_folder)], key=os.path.getctime)

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
