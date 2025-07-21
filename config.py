import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# Telegram Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "7448520005"))
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "7448520005,123456789").split(",") if id]

# Bot Configuration
BOT_CONFIG = {
    "network_url": os.getenv("NETWORK_URL", "https://t.me/GARUD_NETWORK"),
    "support_url": os.getenv("SUPPORT_URL", "https://t.me/GARUD_SUPPORT"),
    "website_url": os.getenv("WEBSITE_URL", "https://mambareturns.store"),
    "bot_username": os.getenv("BOT_USERNAME", "QUEEN_SBOT"),
    "max_message_length": 4000,
    "rate_limit_per_user": 5,
    "conversation_history_size": 10,
    "allowed_chats": [chat for chat in os.getenv("ALLOWED_CHATS", "").split(",") if chat],
    "blocked_users": [user for user in os.getenv("BLOCKED_USERS", "").split(",") if user],
}

# Gemini Configuration
GEMINI_CONFIG = {
    "model_name": "gemini-pro",
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "max_output_tokens": 2048,
    "safety_settings": {
        "HARASSMENT": "BLOCK_NONE",
        "HATE_SPEECH": "BLOCK_NONE",
        "SEXUALLY_EXPLICIT": "BLOCK_NONE",
        "DANGEROUS_CONTENT": "BLOCK_NONE"
    }
}

# Logging Configuration
LOGGING_CONFIG = {
    "log_file": "logs/bot.log",
    "max_bytes": 10485760,
    "backup_count": 5,
    "log_level": "INFO"
}

# Create logs directory if not exists
Path("logs").mkdir(exist_ok=True)
