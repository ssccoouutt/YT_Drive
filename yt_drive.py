import os
import requests
from telegram import Update, InputFile
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Replace with your Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Send me a direct download link, and I'll upload it back to you!")

def handle_document_link(update: Update, context: CallbackContext) -> None:
    url = update.message.text

    # Validate the URL
    if not url.startswith(("http://", "https://")):
        update.message.reply_text("Please send a valid direct download link.")
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

        # Upload the file back to Telegram
        with open(file_name, "rb") as file:
            update.message.reply_document(document=InputFile(file))

        # Clean up the temporary file
        os.remove(file_name)

    except Exception as e:
        update.message.reply_text(f"Failed to process the file. Error: {str(e)}")

def main() -> None:
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
