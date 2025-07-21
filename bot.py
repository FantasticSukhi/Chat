import os
import time
import logging
import asyncio
from functools import wraps
from collections import defaultdict
from typing import Optional, List

import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import (
    BOT_TOKEN,
    GEMINI_API_KEY,
    OWNER_ID,
    ADMIN_IDS,
    BOT_CONFIG,
    GEMINI_CONFIG,
    LOGGING_CONFIG
)

# --- Logging Setup ---
logger = logging.getLogger(__name__)

def setup_logging():
    logging.basicConfig(
        level=LOGGING_CONFIG["log_level"],
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOGGING_CONFIG["log_file"], encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

setup_logging()

# --- Rate Limiting ---
user_message_times = defaultdict(list)

def rate_limit(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        now = time.time()
        
        user_message_times[user_id] = [t for t in user_message_times[user_id] if now - t < 1]
        
        if len(user_message_times[user_id]) >= BOT_CONFIG["rate_limit_per_user"]:
            await update.message.reply_text("🚫 You're sending messages too fast. Please wait a moment.")
            logger.warning(f"Rate limit exceeded for user {user_id}")
            return
        
        user_message_times[user_id].append(now)
        return await func(update, context)
    return wrapper

# --- Conversation History ---
user_conversations = defaultdict(list)

def manage_conversation_history(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_message = update.message.text
        
        user_conversations[user_id].append({"role": "user", "content": user_message})
        
        if len(user_conversations[user_id]) > BOT_CONFIG["conversation_history_size"]:
            user_conversations[user_id] = user_conversations[user_id][-BOT_CONFIG["conversation_history_size"]:]
        
        result = await func(update, context)
        
        if result and isinstance(result, str):
            user_conversations[user_id].append({"role": "assistant", "content": result})
        
        return result
    return wrapper

# --- Initialize Gemini ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_CONFIG["model_name"])

# --- Utility Functions ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def split_long_message(text: str, max_length: int = BOT_CONFIG["max_message_length"]) -> List[str]:
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

async def send_long_message(update: Update, text: str):
    parts = split_long_message(text)
    for part in parts:
        await update.message.reply_text(part)

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    if str(user.id) in BOT_CONFIG["blocked_users"]:
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🌐 Network", url=BOT_CONFIG["network_url"]),
         InlineKeyboardButton("🆘 Support", url=BOT_CONFIG["support_url"])],
        [InlineKeyboardButton("🌐 Website", url=BOT_CONFIG["website_url"]),
         InlineKeyboardButton("📜 Commands", callback_data="help")]
    ]
    
    welcome_message = f"""
👋 Hello {user.mention_html()}!

I'm an advanced AI chatbot powered by Google Gemini. I can understand and respond in multiple languages with context awareness.

💡 <b>Features:</b>
- Multilingual conversations
- Context-aware responses
- Natural dialogue flow
- Advanced AI capabilities

📌 Use /help to see all available commands.
🔍 Just send me a message to start chatting!
"""
    
    await update.message.reply_html(
        welcome_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )
    logger.info(f"New user started: {user.id} - {user.full_name}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = """
<b>🤖 Bot Commands:</b>

/start - Start the bot
/help - Show this help message
/ping - Check bot latency
/stats - Get bot statistics (Admin only)
/clear - Clear conversation history

<b>🎯 Features:</b>
- Supports 100+ languages
- Remembers conversation context
- Safe and moderated responses
- Fast and reliable

<b>🔧 Admin Commands:</b>
/broadcast - Send message to all users
/block - Block a user
/unblock - Unblock a user
"""
    await update.message.reply_html(help_text)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start_time = time.time()
    message = await update.message.reply_text("🏓 Pong!")
    end_time = time.time()
    latency = round((end_time - start_time) * 1000, 2)
    
    await message.edit_text(f"🏓 Pong!\n⏳ Bot Latency: {latency}ms\n🔄 Gemini API: Online")

@rate_limit
@manage_conversation_history
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    user = update.effective_user
    user_message = update.message.text
    
    if str(user.id) in BOT_CONFIG["blocked_users"]:
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return None
    
    try:
        logger.info(f"Processing message from {user.id}: {user_message[:50]}...")
        
        response = model.generate_content(
            user_message,
            generation_config=genai.types.GenerationConfig(
                temperature=GEMINI_CONFIG["temperature"],
                top_p=GEMINI_CONFIG["top_p"],
                top_k=GEMINI_CONFIG["top_k"],
                max_output_tokens=GEMINI_CONFIG["max_output_tokens"],
            ),
            safety_settings=[
                {"category": k, "threshold": v} 
                for k, v in GEMINI_CONFIG["safety_settings"].items()
            ]
        )
        
        await send_long_message(update, response.text)
        return response.text
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        await update.message.reply_text("⚠️ An error occurred while processing your message. Please try again later.")
        return None

# --- Admin Commands ---
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 This command is only available for admins.")
        return
    
    stats_text = f"""
<b>📊 Bot Statistics</b>

👥 Total Users: {len(user_conversations)}
💬 Active Conversations: {sum(1 for conv in user_conversations.values() if len(conv) > 0)}
🔄 Rate Limited Users: {sum(1 for times in user_message_times.values() if len(times) >= BOT_CONFIG["rate_limit_per_user"])}
"""
    await update.message.reply_html(stats_text)

async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_conversations[user_id] = []
    await update.message.reply_text("🗑️ Your conversation history has been cleared.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 This command is only available for admins.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = " ".join(context.args)
    broadcast_count = 0
    
    for user_id in user_conversations.keys():
        try:
            await context.bot.send_message(user_id, f"📢 Broadcast:\n\n{message}")
            broadcast_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {str(e)}")
    
    await update.message.reply_text(f"📢 Broadcast sent to {broadcast_count} users.")

# --- Error Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)
    if update.effective_message:
        await update.effective_message.reply_text("⚠️ An unexpected error occurred. The admin has been notified.")

# --- Setup Commands Menu ---
async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show help"),
        BotCommand("ping", "Check bot status"),
        BotCommand("clear", "Clear your history"),
    ])

# --- Main Application ---
def create_application():
    """Create and configure the Telegram application."""
    return Application.builder() \
        .token(BOT_TOKEN) \
        .connect_timeout(30) \
        .read_timeout(30) \
        .write_timeout(30) \
        .pool_timeout(30) \
        .post_init(post_init) \
        .build()
        
    return Application.builder() \
        .token(BOT_TOKEN) \
        .defaults(defaults) \
        .post_init(post_init) \
        .build()

def setup_handlers(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("clear", clear_history))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

async def run_bot():
    application = create_application()
    setup_handlers(application)
    
    await application.initialize()
    await application.start()
    logger.info("Bot is now running continuously...")
    
    # Keep the application running
    while True:
        await asyncio.sleep(3600)

def main():
    if not BOT_TOKEN:
        logger.error("Invalid Telegram bot token!")
        return

    # Run the bot with restart capability
    while True:
        try:
            asyncio.run(run_bot())
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Fatal error: {str(e)}. Restarting in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    main()
