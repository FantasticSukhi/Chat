# maiimport logging
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import config
except ImportError:
    print("Error: config.py not found. Please create config.py with your API keys.")
    sys.exit(1)

import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
)
from telegram.constants import ParseMode
import asyncio

# MongoDB imports
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- MongoDB Initialization ---
mongo_client = None
db_collection = None # This will store the reference to the 'cloned_bots' collection

def initialize_mongodb():
    """Initializes the MongoDB client and returns the collection."""
    global mongo_client, db_collection
    if not config.MONGO_DB_URL or config.MONGO_DB_URL == "YOUR_MONGODB_CONNECTION_STRING":
        logger.error("MONGO_DB_URL is not set in config.py. MongoDB will not be initialized.")
        return None

    try:
        mongo_client = MongoClient(config.MONGO_DB_URL)
        # The ping command is cheap and does not require auth.
        mongo_client.admin.command('ping')
        logger.info("MongoDB connection successful.")
        
        # Assuming a database named 'telegram_bot_db' and a collection 'cloned_bots'
        db = mongo_client.telegram_bot_db
        db_collection = db.cloned_bots
        logger.info("MongoDB database and collection selected.")
        return db_collection
    except ConnectionFailure as e:
        logger.error(f"MongoDB connection failed: {e}")
        return None
    except OperationFailure as e:
        logger.error(f"MongoDB operation failed (e.g., authentication): {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during MongoDB initialization: {e}")
        return None

# Attempt to initialize MongoDB at startup
db_collection = initialize_mongodb()
if not db_collection:
    logger.error("MongoDB connection could not be established. /clone and /list_clones commands will not work.")


# --- Gemini API Configuration ---
if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "YOUR_GEMINI_API_KEY":
    logger.error("GEMINI_API_KEY is not set in config.py. Please update it.")
    sys.exit(1)
genai.configure(api_key=config.GEMINI_API_KEY)

# Initialize the Gemini model
model = genai.GenerativeModel("gemini-2.0-flash")

# --- Conversation States for /clone command ---
AWAITING_TOKEN = 1

# --- Helper Functions ---
def is_owner(user_id):
    """Checks if the given user_id is the bot owner."""
    return user_id == config.OWNER_ID

# get_user_id_from_auth is no longer needed as we use Telegram user ID directly

# --- Telegram Bot Handlers ---

async def start(update: Update, context):
    """Sends a welcome message with buttons when the /start command is issued."""
    user = update.effective_user
    logger.info(f"User {user.full_name} ({user.id}) started the bot.")

    # Define the inline keyboard buttons
    keyboard = [
        [
            InlineKeyboardButton("🌐 Network", url="https://t.me/GARUD_NETWORK"), # Replace with your network link
            InlineKeyboardButton("🆘 Support", url="https://t.me/GARUD_SUPPORT"), # Replace with your support link
        ],
        [
            InlineKeyboardButton("🌐 Website", url="https://mambareturns.store"),
            InlineKeyboardButton("👑 Owner", callback_data="owner_info"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Beautiful welcome message
    welcome_message = (
        f"👋 Hello, {user.mention_html()}!\n\n"
        "I'm your friendly AI companion, ready to chat with you in any language. "
        "I use Mamba's powerful AI to understand and respond to your messages.\n\n"
        "Feel free to ask me anything or just say hi! 😊\n\n"
        "Here are some quick links:"
    )

    await update.message.reply_html(
        welcome_message,
        reply_markup=reply_markup
    )

async def ping(update: Update, context):
    """Responds with 'Pong!' to the /ping command."""
    logger.info(f"Received /ping command from {update.effective_user.full_name}.")
    await update.message.reply_text("Pong!")

async def help_command(update: Update, context):
    """Sends a help message with available commands."""
    logger.info(f"Received /help command from {update.effective_user.full_name}.")
    help_text = (
        "Here's what I can do:\n\n"
        "💬 Send me any message, and I'll chat with you using AI.\n"
        "Commands:\n"
        "/start - Get a welcome message and useful links.\n"
        "/ping - Check if the bot is responsive.\n"
        "/help - Show this help message.\n"
        "/clone - Register your own bot token for 'cloning' purposes.\n"
        "/list_clones - (Owner only) List registered bot tokens.\n\n"
        "I can understand and respond in almost any language thanks to Gemini AI!"
    )
    await update.message.reply_text(help_text)

async def button_callback_handler(update: Update, context):
    """Handles callback queries from inline keyboard buttons."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    if query.data == "owner_info":
        owner_id_str = str(config.OWNER_ID) if config.OWNER_ID != "YOUR_OWNER_TELEGRAM_ID" else "Not configured"
        await query.edit_message_text(text=f"The bot owner's Telegram ID is: `{owner_id_str}`\n\n"
                                           "Please note: This ID is for informational purposes. "
                                           "Do not share sensitive information.",
                                      parse_mode=ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text="Unknown button action.")

# --- Clone Command Handlers ---
async def clone_start(update: Update, context):
    """Starts the /clone conversation, asking for the bot token."""
    if not db_collection:
        await update.message.reply_text("MongoDB is not initialized. Cannot use /clone function.")
        return ConversationHandler.END

    await update.message.reply_text(
        "Please send me the bot token you want to register for 'cloning'.\n"
        "This token will be stored for future reference. To cancel, send /cancel."
    )
    return AWAITING_TOKEN

async def receive_bot_token(update: Update, context):
    """Receives the bot token from the user and stores it in MongoDB."""
    bot_token = update.message.text.strip()
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name

    # Basic token validation (Telegram bot tokens usually have a specific format)
    if not (len(bot_token) > 30 and ':' in bot_token):
        await update.message.reply_text(
            "That doesn't look like a valid Telegram bot token. "
            "Please send a correct token or /cancel."
        )
        return AWAITING_TOKEN # Stay in this state

    try:
        # Store the token in MongoDB
        # MongoDB automatically creates _id for new documents
        await asyncio.to_thread(db_collection.insert_one, {
            'cloner_telegram_id': user_id,
            'cloner_telegram_name': user_name,
            'bot_token': bot_token,
            'registered_at': datetime.now() # Using Python's datetime for timestamp
        })
        
        await update.message.reply_text(
            "✅ Bot token registered successfully!\n\n"
            "**Important:** This registration stores your token for potential future use by the bot owner "
            "and yourself. It does NOT automatically launch a new bot instance on this server. "
            "Running separate bot instances requires additional server setup (e.g., process management, Docker)."
        )
        logger.info(f"User {user_name} ({user_id}) registered a bot token.")
        return ConversationHandler.END # End the conversation

    except Exception as e:
        logger.error(f"Error storing bot token for user {user_id}: {e}")
        await update.message.reply_text(
            "An error occurred while trying to register your token. Please try again later."
        )
        return ConversationHandler.END # End the conversation on error

async def cancel_clone(update: Update, context):
    """Cancels the /clone conversation."""
    await update.message.reply_text("Cloning process cancelled.")
    return ConversationHandler.END

async def list_clones(update: Update, context):
    """Lists all registered bot tokens (owner only)."""
    if not db_collection:
        await update.message.reply_text("MongoDB is not initialized. Cannot list clones.")
        return

    if not is_owner(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    logger.info(f"Owner {update.effective_user.full_name} ({update.effective_user.id}) requested list of clones.")

    try:
        # Retrieve all documents from the 'cloned_bots' collection
        # Use asyncio.to_thread for blocking MongoDB operations
        docs = await asyncio.to_thread(db_collection.find)
        
        clones_list = []
        # Convert cursor to list to iterate over it
        for doc in list(docs):
            clones_list.append(
                f"- User ID: `{doc.get('cloner_telegram_id', 'N/A')}` "
                f"(Name: {doc.get('cloner_telegram_name', 'N/A')})\n"
                f"  Token (first 10 chars): `{doc.get('bot_token', 'N/A')[:10]}...`"
            )

        if clones_list:
            response_text = "Registered Bot Tokens:\n" + "\n".join(clones_list)
        else:
            response_text = "No bot tokens registered yet."

        await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error listing cloned bots: {e}")
        await update.message.reply_text("An error occurred while trying to list registered tokens.")

async def chat_message(update: Update, context):
    """Processes incoming text messages and responds using the Gemini API."""
    user_message = update.message.text
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user_name = update.effective_user.full_name

    logger.info(f"Received message from {user_name} (Chat ID: {chat_id}, Type: {chat_type}): {user_message}")

    if not user_message:
        logger.warning("Received an empty message.")
        return

    # Indicate that the bot is typing
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        # Generate content using the Gemini model
        response = model.generate_content(user_message)

        # Extract the text from the Gemini response
        if response.candidates and response.candidates[0].content.parts:
            bot_response = response.candidates[0].content.parts[0].text
        else:
            bot_response = "I'm sorry, I couldn't generate a response at this moment."
            logger.warning(f"Gemini API returned no valid content for message: {user_message}")

    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        bot_response = "Oops! Something went wrong while processing your request. Please try again later."

    # Send the generated response back to the user/group
    await update.message.reply_text(bot_response)

async def error_handler(update: Update, context):
    """Log Errors caused by Updates."""
    logger.warning(f"Update {update} caused error {context.error}")
    if context.error:
        logger.error(f"Error details: {context.error}")


def main():
    """Starts the bot."""
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("TELEGRAM_BOT_TOKEN is not set in config.py. Please update it.")
        sys.exit(1)

    if not config.OWNER_ID or config.OWNER_ID == "YOUR_OWNER_TELEGRAM_ID":
        logger.warning("OWNER_ID is not set in config.py. Some features (like /list_clones) might not work as expected.")

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Conversation Handler for /clone
    clone_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("clone", clone_start)],
        states={
            AWAITING_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_token)],
        },
        fallbacks=[CommandHandler("cancel", cancel_clone)],
    )

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list_clones", list_clones))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(clone_conversation_handler) # Add the conversation handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message))

    # Register error handler
    application.add_error_handler(error_handler)

    logger.info("Bot is starting... Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Import datetime here as it's only used within async functions
    from datetime import datetime
    main()
