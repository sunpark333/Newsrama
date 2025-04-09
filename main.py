import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
)
from telegram.error import TelegramError
import sqlite3
import datetime
import os
from dotenv import load_dotenv
from flask import Flask

       app = Flask(__name__)
       
       @app.route('/')
       def health_check():
           return "OK", 200
       
       if __name__ == '__main__':
           import threading
           threading.Thread(target=app.run, kwargs={'host':'0.0.0.0','port':8000}).start()

# Load environment variables
load_dotenv()

# Configuration from .env
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS').split(',')]  # Multiple admin IDs
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID'))  # Negative channel ID
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME', '@your_channel')  # Default value if not set
DB_NAME = os.getenv('DB_NAME', 'news_bot.db')  # Default database name
WELCOME_IMAGE_FILE_ID = os.getenv('WELCOME_IMAGE_FILE_ID')  # File ID of the welcome image

# Logging setup (unchanged)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class NewsBotDatabase:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS active_chats
                       (chat_id INTEGER PRIMARY KEY,
                        chat_type TEXT,
                        title TEXT,
                        registered_at TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS news_posts
                       (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT,
                        media_type TEXT,
                        media_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()

    def add_chat(self, chat_id, chat_type, title):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT OR IGNORE INTO active_chats
                       (chat_id, chat_type, title, registered_at)
                       VALUES (?, ?, ?, ?)''',
                       (chat_id, chat_type, title, datetime.datetime.now()))
        self.conn.commit()

    def get_all_chats(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT chat_id, chat_type, title FROM active_chats")
        return cursor.fetchall()

    def save_news(self, content, media_type=None, media_id=None):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT INTO news_posts
                       (content, media_type, media_id)
                       VALUES (?, ?, ?)''',
                       (content, media_type, media_id))
        self.conn.commit()
        return cursor.lastrowid

db = NewsBotDatabase()

async def send_log(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Send message to log channel"""
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=f"📝 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{message}"
        )
    except Exception as e:
        logger.error(f"Error sending message to log channel: {e}")

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for starting the bot"""
    chat = update.effective_chat
    db.add_chat(chat.id, chat.type, chat.title or "Private Chat")

    # Create attractive button menu
    keyboard = [
        [InlineKeyboardButton("➕ ADD ME TO YOUR GROUP ➕", url=f"https://t.me/{context.bot.username}?startgroup=true")],
        [InlineKeyboardButton("📢 JOIN OUR NEWS CHANNEL 📢", url=f"https://t.me/{CHANNEL_USERNAME}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    log_msg = (
        f"🆕 New chat registered\n\n"
        f"📌 Type: {'Group' if chat.type in ['group', 'supergroup'] else 'Private'}\n"
        f"🆔 ID: {chat.id}\n"
        f"🏷️ Name: {chat.title or 'N/A'}\n"
        f"👤 User: {update.effective_user.full_name} (@{update.effective_user.username or 'N/A'})"
    )

    await send_log(context, log_msg)

    # Enhanced welcome message with photo if available
    welcome_text = (
        "🌟 *WELCOME TO NEWS BOT* 🌟\n\n"
        "📰 *Stay updated with the latest news!*\n"
        "🔔 Get instant news updates directly in this chat\n"
        "📢 Broadcast news to all subscribed chats (admin only)\n\n"
        "⚡ *Available Commands:*\n"
        "• /start - Show welcome message\n"
        "• /stats - Show bot statistics\n\n"
        "👇 *Use the buttons below to get started:*"
    )

    try:
        if WELCOME_IMAGE_FILE_ID:
            await update.message.reply_photo(
                photo=WELCOME_IMAGE_FILE_ID,
                caption=welcome_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error sending welcome message: {e}")
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler when bot is added to new group"""
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            chat = update.effective_chat
            db.add_chat(chat.id, chat.type, chat.title)

            log_msg = (
                f"➕ Bot added to new group\n\n"
                f"🏷️ Group name: {chat.title}\n"
                f"🆔 ID: {chat.id}\n"
                f"👤 Added by: {update.effective_user.full_name}"
            )
            
            await send_log(context, log_msg)
            await context.bot.send_message(
                chat_id=chat.id,
                text="📢 *News Bot Activated!* This group will now receive news updates.\n\n"
                     "⚠️ Please make the bot admin and grant 'Send Messages' permission.\n\n"
                     "Type /start to see bot features or /stats to view statistics!",
                parse_mode='Markdown'
            )

async def post_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for admins to post news"""
    if update.effective_user.id not in ADMIN_IDS:
        return  # Don't respond to unauthorized users

    # Get media and text
    content = update.message.caption or update.message.text or ""
    media_type = None
    media_id = None

    if update.message.photo:
        media_type = "photo"
        media_id = update.message.photo[-1].file_id
    elif update.message.video:
        media_type = "video"
        media_id = update.message.video.file_id

    # Save to database
    post_id = db.save_news(content, media_type, media_id)

    # Broadcast to all chats (except admin)
    success = 0
    failed = 0
    all_chats = [chat for chat in db.get_all_chats() if chat[0] not in ADMIN_IDS]  # Exclude admin chats
    total_chats = len(all_chats)

    progress_msg = await context.bot.send_message(
        chat_id=LOG_CHANNEL_ID,
        text=f"⏳ Starting news broadcast...\n\n"
             f"📌 Post ID: {post_id}\n"
             f"🗂️ Total chats: {total_chats}\n"
             f"✅ Success: 0\n"
             f"❌ Failed: 0"
    )

    for chat_id, chat_type, chat_title in all_chats:
        try:
            if media_type == "photo":
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=media_id,
                    caption=content
                )
            elif media_type == "video":
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=media_id,
                    caption=content
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=content
                )
            success += 1
        except TelegramError as e:
            failed += 1
            logger.error(f"Failed to send to {chat_id}: {e}")
        
        # Update progress (every 10 chats)
        if (success + failed) % 10 == 0:
            await context.bot.edit_message_text(
                chat_id=LOG_CHANNEL_ID,
                message_id=progress_msg.message_id,
                text=f"⏳ News broadcast progress...\n\n"
                     f"📌 Post ID: {post_id}\n"
                     f"🗂️ Total chats: {total_chats}\n"
                     f"✅ Success: {success}\n"
                     f"❌ Failed: {failed}"
            )

    # Final log
    log_msg = (
        f"📢 News broadcast complete\n\n"
        f"🆔 Post ID: {post_id}\n"
        f"📝 Content: {content[:50]}...\n\n"
        f"📊 Stats:\n"
        f"• Total chats: {total_chats}\n"
        f"• Success: {success}\n"
        f"• Failed: {failed}\n\n"
        f"👤 Posted by: {update.effective_user.full_name}"
    )

    if media_type:
        log_msg += f"\n🖼️ Media type: {media_type}"

    await send_log(context, log_msg)
    await update.message.reply_text(
        f"✅ News successfully sent\n"
        f"📌 Post ID: {post_id}\n"
        f"✅ Success in {success} chats\n"
        f"❌ Failed in {failed} chats"
    )

async def broadcast_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for admins to broadcast polls"""
    if update.effective_user.id not in ADMIN_IDS:
        return

    # Check if the message is a reply to a poll
    if not update.message.reply_to_message or not update.message.reply_to_message.poll:
        await update.message.reply_text("⚠️ Please reply to a poll message with /broadcastpoll to broadcast it.")
        return

    original_poll = update.message.reply_to_message.poll
    question = original_poll.question
    options = [option.text for option in original_poll.options]
    is_anonymous = original_poll.is_anonymous
    allows_multiple_answers = original_poll.allows_multiple_answers
    explanation = original_poll.explanation if original_poll.explanation else None
    open_period = original_poll.open_period if original_poll.open_period else None

    # Broadcast to all chats (except admin)
    success = 0
    failed = 0
    all_chats = [chat for chat in db.get_all_chats() if chat[0] not in ADMIN_IDS]  # Exclude admin chats
    total_chats = len(all_chats)

    progress_msg = await context.bot.send_message(
        chat_id=LOG_CHANNEL_ID,
        text=f"⏳ Starting poll broadcast...\n\n"
             f"📌 Question: {question[:20]}...\n"
             f"🗂️ Total chats: {total_chats}\n"
             f"✅ Success: 0\n"
             f"❌ Failed: 0"
    )

    for chat_id, chat_type, chat_title in all_chats:
        try:
            await context.bot.send_poll(
                chat_id=chat_id,
                question=question,
                options=options,
                is_anonymous=is_anonymous,
                allows_multiple_answers=allows_multiple_answers,
                explanation=explanation,
                open_period=open_period
            )
            success += 1
        except TelegramError as e:
            failed += 1
            logger.error(f"Failed to send poll to {chat_id}: {e}")
        
        # Update progress (every 10 chats)
        if (success + failed) % 10 == 0:
            await context.bot.edit_message_text(
                chat_id=LOG_CHANNEL_ID,
                message_id=progress_msg.message_id,
                text=f"⏳ Poll broadcast progress...\n\n"
                     f"📌 Question: {question[:20]}...\n"
                     f"🗂️ Total chats: {total_chats}\n"
                     f"✅ Success: {success}\n"
                     f"❌ Failed: {failed}"
            )

    # Final log
    log_msg = (
        f"📊 Poll broadcast complete\n\n"
        f"❓ Question: {question[:50]}...\n"
        f"📊 Options: {', '.join([opt[:10] for opt in options])}...\n\n"
        f"📊 Stats:\n"
        f"• Total chats: {total_chats}\n"
        f"• Success: {success}\n"
        f"• Failed: {failed}\n\n"
        f"👤 Posted by: {update.effective_user.full_name}"
    )

    await send_log(context, log_msg)
    await update.message.reply_text(
        f"✅ Poll successfully sent\n"
        f"❓ Question: {question[:30]}...\n"
        f"✅ Success in {success} chats\n"
        f"❌ Failed in {failed} chats"
    )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics with back button"""
    all_chats = db.get_all_chats()
    total_chats = len(all_chats)
    groups = sum(1 for _, chat_type, _ in all_chats if chat_type in ['group', 'supergroup'])
    private = total_chats - groups

    stats_msg = (
        f"📊 *Bot Statistics*\n\n"
        f"• Total chats: *{total_chats}*\n"
        f"  ├─ Groups: *{groups}*\n"
        f"  └─ Private: *{private}*\n\n"
        f"🆔 Log channel: `{LOG_CHANNEL_ID}`"
    )

    # Create keyboard with back button
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        text=stats_msg,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

    # Log that someone checked stats
    logger.info(f"Statistics checked by user: {update.effective_user.full_name} (ID: {update.effective_user.id})")
    await send_log(context, f"📊 Statistics checked\n👤 User: {update.effective_user.full_name}")

async def handle_back_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back button callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_start":
        # Reuse the start handler's welcome message
        chat = update.effective_chat
        
        # Create the same keyboard as in handle_start
        keyboard = [
            [InlineKeyboardButton("➕ ADD ME TO YOUR GROUP ➕", url=f"https://t.me/{context.bot.username}?startgroup=true")],
            [InlineKeyboardButton("📢 JOIN OUR NEWS CHANNEL 📢", url=f"https://t.me/{CHANNEL_USERNAME}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        welcome_text = (
            "🌟 *WELCOME TO NEWS BOT* 🌟\n\n"
            "📰 *Stay updated with the latest news!*\n"
            "🔔 Get instant news updates directly in this chat\n"
            "📢 Broadcast news to all subscribed chats (admin only)\n\n"
            "⚡ *Available Commands:*\n"
            "• /start - Show welcome message\n"
            "• /stats - Show bot statistics\n"
            "• /broadcastpoll - Broadcast a poll (reply to a poll)\n\n"
            "👇 *Use the buttons below to get started:*"
        )

        try:
            if WELCOME_IMAGE_FILE_ID:
                await query.message.reply_photo(
                    photo=WELCOME_IMAGE_FILE_ID,
                    caption=welcome_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await query.message.reply_text(
                    welcome_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")
            await query.message.reply_text(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        # Delete the stats message
        await query.message.delete()

def main():
    """Launch the bot"""
    app = Application.builder().token(TOKEN).build()

    # Admin filter (only for post_news)
    admin_filter = filters.User(ADMIN_IDS)

    # Command handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("broadcastpoll", broadcast_poll, filters=admin_filter))
    
    # Add callback handler for back button
    app.add_handler(CallbackQueryHandler(handle_back_button))

    # Handlers for admin messages (without commands)
    app.add_handler(MessageHandler(filters.PHOTO & admin_filter, post_news))
    app.add_handler(MessageHandler(filters.VIDEO & admin_filter, post_news))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & admin_filter, post_news))

    # Handler for new members
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))

    # Start the bot
    print("🤖 News Bot is now running...")
    logger.info("Bot started successfully")
    app.run_polling()

if __name__ == '__main__':
    main()
