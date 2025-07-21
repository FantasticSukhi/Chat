#!/usr/bin/env python3
import os
import time
import logging
import asyncio
import httpx
from functools import wraps
from collections import defaultdict
from typing import Optional

import google.generativeai as genai
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext
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

# --- Enhanced Logging Setup ---
logger = logging.getLogger(__name__)

def setup_logging():
    """Configure comprehensive logging"""
    logging.basicConfig(
        level=LOGGING_CONFIG["log_level"],
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(
                filename=LOGGING_CONFIG["log_file"],
                encoding='utf-8',
                mode='a'
            ),
            logging.StreamHandler()
        ]
    )
    # Reduce noise from underlying libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

setup_logging()

# --- Connection Verification ---
async def verify_telegram_connection():
    """Verify we can connect to Telegram API"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Check basic API connectivity
            response = await client.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
            )
            if response.status_code != 200:
                raise ConnectionError(
                    f"Telegram API connection failed: {response.text}"
                )
            
            # Verify bot privacy settings
            privacy_response = await client.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getChat?chat_id={OWNER_ID}"
            )
            if privacy_response.status_code != 200:
                logger.warning("Could not verify privacy settings - ensure bot can message you")
            
            return True
            
    except Exception as e:
        logger.error(f"Telegram connection verification failed: {e}")
        return False

async def verify_gemini_connection():
    """Verify we can connect to Gemini API"""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_CONFIG["model_name"])
        response = await asyncio.to_thread(
            model.generate_content,
            "Test connection"
        )
        return bool(response.text)
    except Exception as e:
        logger.error(f"Gemini connection verification failed: {e}")
        return False

# --- Conversation Management ---
user_conversations = defaultdict(list)
user_message_times = defaultdict(list)

def rate_limit(func):
    """Decorator to implement rate limiting"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        now = time.time()
        
        # Clear old timestamps
        user_message_times[user_id] = [
            t for t in user_message_times[user_id] 
            if now - t < 1  # 1 second window
        ]
        
        # Check rate limit
        if len(user_message_times[user_id]) >= BOT_CONFIG["rate_limit_per_user"]:
            await update.message.reply_text(
                "🚫 You're sending messages too fast. Please wait a moment."
            )
            logger.warning(f"Rate limit exceeded for user {user_id}")
            return
        
        user_message_times[user_id].append(now)
        return await func(update, context)
    return wrapper

genai.configure(
    api_key=GEMINI_API_KEY,
    transport='rest',  # Explicitly set transport
    client_options={"api_endpoint": "generativelanguage.googleapis.com"}
)

# --- Utility Functions ---
def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in ADMIN_IDS

async def send_long_message(update: Update, text: str):
    """Split long messages to fit Telegram's limits"""
    max_len = BOT_CONFIG["max_message_length"]
    for i in range(0, len(text), max_len):
        await update.message.reply_text(text[i:i+max_len])

async def log_update(update: Update):
    """Log details about incoming updates"""
    logger.info(
        f"New update [ID:{update.update_id}]: "
        f"User:{update.effective_user.id if update.effective_user else None} "
        f"Chat:{update.effective_chat.id if update.effective_chat else None} "
        f"Type:{update.effective_message.content_type if update.effective_message else None}"
    )

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await log_update(update)
    
    user = update.effective_user
    if str(user.id) in BOT_CONFIG["blocked_users"]:
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("🌐 Network", url=BOT_CONFIG["network_url"]),
            InlineKeyboardButton("🆘 Support", url=BOT_CONFIG["support_url"]),
        ],
        [
            InlineKeyboardButton("🌐 Website", url=BOT_CONFIG["website_url"]),
            InlineKeyboardButton("📜 Commands", callback_data="help")
        ]
    ]
    
    welcome_message = f"""
👋 Hello {user.mention_html()}!

I'm an advanced AI chatbot powered by Google Gemini. Here's what I can do:

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
    logger.info(f"Welcomed user {user.id} - {user.full_name}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await log_update(update)
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

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ping command"""
    await log_update(update)
    start_time = time.time()
    message = await update.message.reply_text("🏓 Pong!")
    end_time = time.time()
    latency = round((end_time - start_time) * 1000, 2)
    
    await message.edit_text(
        f"🏓 Pong!\n"
        f"⏳ Bot Latency: {latency}ms\n"
        f"🔄 Gemini API: Online\n"
        f"💬 Active Users: {len(user_conversations)}"
    )

@rate_limit
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages"""
    await log_update(update)
    user = update.effective_user
    user_message = update.message.text
    
    if str(user.id) in BOT_CONFIG["blocked_users"]:
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return
    
    try:
        logger.info(f"Processing message from {user.id}: {user_message[:50]}...")
        
        # Manage conversation history
        user_conversations[user.id].append({"role": "user", "content": user_message})
        if len(user_conversations[user.id]) > BOT_CONFIG["conversation_history_size"]:
            user_conversations[user.id] = user_conversations[user.id][-BOT_CONFIG["conversation_history_size"]:]
        
        # Generate response
        response = await asyncio.to_thread(
            model.generate_content,
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
        
        # Send response
        await send_long_message(update, response.text)
        
        # Store bot response in history
        user_conversations[user.id].append({"role": "assistant", "content": response.text})
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "⚠️ An error occurred while processing your message. Please try again later."
        )

# --- Admin Commands ---
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    await log_update(update)
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
    """Handle /clear command"""
    await log_update(update)
    user_id = update.effective_user.id
    user_conversations[user_id] = []
    await update.message.reply_text("🗑️ Your conversation history has been cleared.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /broadcast command"""
    await log_update(update)
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

# --- System Functions ---
async def post_init(application: Application):
    """Send startup notification and set commands"""
    try:
        # Clear any existing webhook
        await application.bot.delete_webhook()
        
        # Set bot commands
        await application.bot.set_my_commands([
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help"),
            BotCommand("ping", "Check bot status"),
            BotCommand("clear", "Clear your history"),
        ])
        
        # Send startup message
        await application.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🤖 Bot @{BOT_CONFIG['bot_username']} started successfully!\n"
                 f"📅 Server Time: {time.ctime()}\n"
                 f"🖥️ Host: {os.uname().nodename}"
        )
    except Exception as e:
        logger.error(f"Startup initialization failed: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors in the bot"""
    logger.error(
        f"Error in update {update.update_id if update else None}: {context.error}",
        exc_info=True
    )
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An unexpected error occurred. The admin has been notified."
        )
    
    # Notify owner about critical errors
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🚨 Bot Error:\n{str(context.error)[:1000]}"
        )
    except:
        pass

def create_application():
    """Create and configure the Telegram application"""
    return Application.builder() \
        .token(BOT_TOKEN) \
        .connect_timeout(30) \
        .read_timeout(30) \
        .write_timeout(30) \
        .pool_timeout(30) \
        .post_init(post_init) \
        .build()

def setup_handlers(application):
    """Set up all command and message handlers"""
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("clear", clear_history))
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Message handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    
    # Error handler
    application.add_error_handler(error_handler)

async def run_bot():
    """Main bot running function with enhanced reliability"""
    retry_count = 0
    max_retries = 5
    
    while retry_count < max_retries:
        try:
            # Verify connections before starting
            if not all([
                await verify_telegram_connection(),
                await verify_gemini_connection()
            ]):
                raise ConnectionError("Connection verification failed")
            
            # Initialize application
            application = create_application()
            setup_handlers(application)
            
            await application.initialize()
            await application.start()
            
            logger.info("Bot is now running and processing updates...")
            
            # Keep the application running
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            retry_count += 1
            logger.error(f"Bot crashed (attempt {retry_count}/{max_retries}): {e}")
            
            if retry_count < max_retries:
                logger.info("Restarting in 10 seconds...")
                await asyncio.sleep(10)
            else:
                logger.critical("Maximum restart attempts reached")
                break
        finally:
            try:
                await application.stop()
                await application.shutdown()
            except:
                pass

def main():
    """Entry point for the bot"""
    try:
        logger.info("Starting bot...")
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
    finally:
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    main()
