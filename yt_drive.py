import os
import subprocess
import yt_dlp
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackContext
from telegram.error import TelegramError

# API Token for the bot (obtained from environment variable)
API_TOKEN = os.environ.get('API_TOKEN')  # Fetch API_TOKEN from environment variable

# Telegram size limit (50 MB)
TELEGRAM_MAX_SIZE_MB = 50

# Function to handle real-time download progress
async def download_progress(d, message):
    if d['status'] == 'downloading':
        percentage = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
        # Update the progress by editing the same message
        if int(percentage) % 10 == 0:  # Update every 10% to avoid too many edits
            await message.edit_text(f"Download progress: {percentage:.2f}%")
    elif d['status'] == 'finished':
        await message.edit_text("Download complete, processing file...")

# Function to download videos or audios (YouTube, Twitter/X, and TikTok)
async def download_video(url, destination_folder, message, format="video"):
    try:
        # Determine the format
        if format == "audio":
            format_type = 'bestaudio/best'
            ext = 'mp3'
        else:
            format_type = 'best'
            ext = 'mp4'

        # yt-dlp configuration with progress_hooks
        options = {
            'outtmpl': f'{destination_folder}/%(id)s.%(ext)s',  # Use the video ID to avoid filename issues
            'format': format_type,  # Select the format based on user input
            'restrictfilenames': True,  # Limit special characters
            'progress_hooks': [lambda d: asyncio.create_task(download_progress(d, message))],  # Hook to show real-time progress
        }

        # Download the video or audio
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        print(f"Error during download: {e}")
        return False

# Function to reduce video quality if it's too large using ffmpeg
def reduce_quality_ffmpeg(video_path, output_path, target_size_mb=50):
    try:
        # Command to reduce video quality using ffmpeg
        command = [
            'ffmpeg', '-i', video_path,
            '-b:v', '500k',  # Adjust the video bitrate (can be modified as needed)
            '-vf', 'scale=iw/2:ih/2',  # Reduce resolution by half
            '-c:a', 'aac',  # Encode audio with AAC
            '-b:a', '128k',  # Adjust the audio bitrate
            output_path
        ]

        # Execute the ffmpeg command
        subprocess.run(command, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error reducing video quality with ffmpeg: {e}")
        return False

# Function to handle the /start command
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text('Send a YouTube, Twitter/X, or TikTok link using /download <url>.\n'
                                    'If the file is larger than 50 MB, the quality will be reduced to send it.')

# Function to handle the /download command with format options
async def download(update: Update, context: CallbackContext):
    try:
        # Extract the text sent after the command
        message_text = update.message.text

        # Check if the message contains a valid URL from YouTube, Twitter/X, or TikTok
        if any(domain in message_text for domain in ["https://www.youtube.com/", "https://youtu.be/", "https://twitter.com/", "https://x.com/", "https://www.tiktok.com/"]):
            params = message_text.split(" ")
            url = params[1]  # Extract the URL after the command
            format = "video" if len(params) < 3 or params[2].lower() != "audio" else "audio"
            destination_folder = os.getenv('TEMP', '/tmp')  # Use the default temporary directory provided by Railway

            # Send the initial message and keep it for updates
            message = await update.message.reply_text(f'Starting the {format} download from: {url}')

            # Start the download and update the same message
            success_download = await download_video(url, destination_folder, message, format)

            if not success_download:
                await message.edit_text('Error during the video download. Please try again later.')
                return

            # Get the name of the downloaded file
            video_filename = max([os.path.join(destination_folder, f) for f in os.listdir(destination_folder)], key=os.path.getctime)

            # Check the file size
            file_size_mb = os.path.getsize(video_filename) / (1024 * 1024)
            if file_size_mb > TELEGRAM_MAX_SIZE_MB:
                await message.edit_text(f'The file is too large ({file_size_mb:.2f} MB). '
                                        f'Reducing the quality to meet the 50 MB limit...')

                # Attempt to reduce the quality using ffmpeg
                output_filename = os.path.join(destination_folder, 'compressed_' + os.path.basename(video_filename))
                success_reduce = reduce_quality_ffmpeg(video_filename, output_filename, TELEGRAM_MAX_SIZE_MB)

                if not success_reduce:
                    await message.edit_text('Error reducing the video quality. Please try again later.')
                    return

                # Switch to the compressed file for sending
                video_filename = output_filename

            # Send the video/audio file to the user
            await message.edit_text(f'Sending the {format}...')
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
            await update.message.reply_text('Please provide a valid YouTube, Twitter/X, or TikTok URL.')

    except Exception as e:
        await update.message.reply_text('An unexpected error occurred. Please try again later.')
        print(f"Error in the download function: {e}")

# Main function to run the bot
def main():
    # Create the bot using ApplicationBuilder
    application = ApplicationBuilder().token(API_TOKEN).build()

    # Handled commands
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('download', download))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
