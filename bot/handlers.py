"""Bot handlers for commands, messages, and callbacks."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from telegram import Update, Message, Chat, User as TGUser
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    Application,
)

from bot.config import settings
from bot.database import (
    get_session,
    get_or_create_user,
    get_or_create_chat,
    log_message,
    get_bot_state,
    set_bot_state,
)
from bot.external_api import get_api_client
from bot.keyboards import (
    CallbackAction,
    CallbackData,
    build_main_keyboard,
    build_help_keyboard,
    build_settings_keyboard,
    build_confirmation_keyboard,
    build_admin_keyboard,
)
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Conversation states
WAITING_BROADCAST = 1


async def _get_user_chat(update: Update) -> tuple[Optional[TGUser], Optional[Chat]]:
    """Extract user and chat from update."""
    user = update.effective_user
    chat = update.effective_chat
    return user, chat


async def _ensure_user_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[Optional[TGUser], Optional[Chat]]:
    """Ensure user and chat exist in database."""
    user, chat = await _get_user_chat(update)
    if not user or not chat:
        return user, chat

    async with get_session() as session:
        await get_or_create_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
            is_bot=user.is_bot,
        )
        await get_or_create_chat(
            session,
            chat_id=chat.id,
            chat_type=chat.type,
            title=chat.title,
            username=chat.username,
        )
    return user, chat


# === Command Handlers ===

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user, chat = await _ensure_user_chat(update, context)
    if not user:
        return

    welcome_text = (
        f"👋 Hello <b>{user.first_name or 'there'}</b>!\n\n"
        f"Welcome to <b>{context.bot.name}</b>.\n"
        f"Use the menu below to explore features."
    )

    await update.message.reply_html(
        welcome_text,
        reply_markup=build_main_keyboard(),
    )
    logger.info("start_command", user_id=user.id, chat_id=chat.id if chat else None)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    user, chat = await _ensure_user_chat(update, context)
    if not user:
        return

    help_text = (
        "📖 <b>Help</b>\n\n"
        "<b>Commands:</b>\n"
        "• /start - Show main menu\n"
        "• /help - Show this help\n"
        "• /ping - Check bot latency\n"
        "• /settings - Bot settings\n"
        "• /stats - Your statistics\n\n"
        "<b>Features:</b>\n"
        "• Inline keyboards for navigation\n"
        "• External API integration\n"
        "• Database persistence\n"
        "• Scheduled jobs\n"
        "• Message logging\n\n"
        "Click buttons below to interact!"
    )

    await update.message.reply_html(
        help_text,
        reply_markup=build_help_keyboard(),
    )
    logger.info("help_command", user_id=user.id)


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ping command - measure latency."""
    user, chat = await _ensure_user_chat(update, context)
    if not user:
        return

    start = dt.datetime.now(dt.timezone.utc)
    msg = await update.message.reply_text("🏓 Pong!")
    end = dt.datetime.now(dt.timezone.utc)

    latency = (end - start).total_seconds() * 1000
    await msg.edit_text(f"🏓 Pong! <b>{latency:.1f}ms</b>", parse_mode=ParseMode.HTML)
    logger.info("ping_command", user_id=user.id, latency_ms=latency)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command."""
    user, chat = await _ensure_user_chat(update, context)
    if not user:
        return

    # Get notification preference from DB
    async with get_session() as session:
        notif_key = f"notifications:{user.id}"
        notif_value = await get_bot_state(session, notif_key)
        notifications_enabled = notif_value != "false"

    await update.message.reply_html(
        "⚙️ <b>Settings</b>\n\nConfigure your preferences:",
        reply_markup=build_settings_keyboard(notifications_enabled),
    )
    logger.info("settings_command", user_id=user.id)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command - show user statistics."""
    user, chat = await _ensure_user_chat(update, context)
    if not user:
        return

    async with get_session() as session:
        from bot.database import MessageLog
        from sqlalchemy import func, select

        # Count messages
        result = await session.execute(
            select(func.count(MessageLog.id)).where(MessageLog.user_id == user.id)
        )
        msg_count = result.scalar() or 0

        # Get first message date
        result = await session.execute(
            select(func.min(MessageLog.created_at)).where(MessageLog.user_id == user.id)
        )
        first_msg = result.scalar()

    stats_text = (
        f"📊 <b>Your Statistics</b>\n\n"
        f"• Messages sent: <b>{msg_count}</b>\n"
        f"• First message: <b>{first_msg.strftime('%Y-%m-%d') if first_msg else 'N/A'}</b>\n"
        f"• User ID: <code>{user.id}</code>\n"
    )

    if chat:
        stats_text += f"• Chat ID: <code>{chat.id}</code> ({chat.type})\n"

    await update.message.reply_html(stats_text)
    logger.info("stats_command", user_id=user.id, message_count=msg_count)


# === Message Handlers ===

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular text messages."""
    user, chat = await _ensure_user_chat(update, context)
    if not user or not chat or not update.message:
        return

    message = update.message
    text = message.text or ""

    # Log message
    async with get_session() as session:
        await log_message(
            session,
            message_id=message.message_id,
            user_id=user.id,
            chat_id=chat.id,
            text=text,
            message_type="text",
        )

    # Echo with some info (replace with your logic)
    if text.startswith("/"):
        return  # Let command handlers deal with it

    response = (
        f"📝 You said: <i>{text}</i>\n\n"
        f"Message ID: <code>{message.message_id}</code>\n"
        f"Chat: <code>{chat.id}</code> ({chat.type})"
    )

    await message.reply_html(response)
    logger.info("text_message", user_id=user.id, chat_id=chat.id, length=len(text))


async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle media messages (photo, document, video, etc.)."""
    user, chat = await _ensure_user_chat(update, context)
    if not user or not chat or not update.message:
        return

    message = update.message
    media_type = "unknown"

    if message.photo:
        media_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.document:
        media_type = "document"
        file_id = message.document.file_id
    elif message.video:
        media_type = "video"
        file_id = message.video.file_id
    elif message.audio:
        media_type = "audio"
        file_id = message.audio.file_id
    elif message.voice:
        media_type = "voice"
        file_id = message.voice.file_id
    elif message.sticker:
        media_type = "sticker"
        file_id = message.sticker.file_id
    else:
        file_id = "unknown"

    # Log message
    async with get_session() as session:
        await log_message(
            session,
            message_id=message.message_id,
            user_id=user.id,
            chat_id=chat.id,
            text=message.caption,
            message_type=media_type,
        )

    await message.reply_html(
        f"📎 Received <b>{media_type}</b>\n"
        f"File ID: <code>{file_id}</code>"
    )
    logger.info("media_message", user_id=user.id, chat_id=chat.id, media_type=media_type)


# === Callback Query Handlers ===

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main callback query router."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()  # Acknowledge immediately

    user, chat = await _ensure_user_chat(update, context)
    if not user:
        return

    try:
        callback_data = CallbackData.unpack(query.data)
    except ValueError:
        logger.warning("invalid_callback_data", data=query.data, user_id=user.id)
        await query.edit_message_text("❌ Invalid callback data")
        return

    logger.info("callback_query", user_id=user.id, action=callback_data.action, payload=callback_data.payload)

    # Route to specific handlers
    if callback_data.action == CallbackAction.MAIN_MENU:
        await _handle_main_menu(query, context)
    elif callback_data.action == CallbackAction.HELP:
        await _handle_help(query, context)
    elif callback_data.action == CallbackAction.SETTINGS:
        await _handle_settings(query, context)
    elif callback_data.action == CallbackAction.EXAMPLE_API_CALL:
        await _handle_example_api_call(query, context)
    elif callback_data.action == CallbackAction.EXAMPLE_DB_QUERY:
        await _handle_example_db_query(query, context)
    elif callback_data.action == CallbackAction.TOGGLE_NOTIFICATIONS:
        await _handle_toggle_notifications(query, context)
    elif callback_data.action == CallbackAction.ADMIN_STATS:
        await _handle_admin_stats(query, context)
    elif callback_data.action == CallbackAction.ADMIN_BROADCAST:
        await _handle_admin_broadcast(query, context)
    elif callback_data.action in (CallbackAction.CONFIRM_YES, CallbackAction.CONFIRM_NO):
        await _handle_confirmation(query, context, callback_data)
    else:
        await query.edit_message_text(f"🚧 Action <code>{callback_data.action}</code> not implemented yet.", parse_mode=ParseMode.HTML)


async def _handle_main_menu(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show main menu."""
    await query.edit_message_html(
        "🏠 <b>Main Menu</b>\n\nChoose an option:",
        reply_markup=build_main_keyboard(),
    )


async def _handle_help(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help."""
    help_text = (
        "📖 <b>Help</b>\n\n"
        "<b>Commands:</b>\n"
        "• /start - Show main menu\n"
        "• /help - Show this help\n"
        "• /ping - Check bot latency\n"
        "• /settings - Bot settings\n"
        "• /stats - Your statistics\n\n"
        "<b>Features:</b>\n"
        "• Inline keyboards for navigation\n"
        "• External API integration\n"
        "• Database persistence\n"
        "• Scheduled jobs\n"
        "• Message logging\n"
    )
    await query.edit_message_html(help_text, reply_markup=build_help_keyboard())


async def _handle_settings(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show settings."""
    user = query.from_user
    async with get_session() as session:
        notif_key = f"notifications:{user.id}"
        notif_value = await get_bot_state(session, notif_key)
        notifications_enabled = notif_value != "false"

    await query.edit_message_html(
        "⚙️ <b>Settings</b>\n\nConfigure your preferences:",
        reply_markup=build_settings_keyboard(notifications_enabled),
    )


async def _handle_example_api_call(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Example: Call external API."""
    await query.edit_message_text("🔄 Calling external API...")

    client = get_api_client()
    response = await client.health_check()

    if response.success:
        text = (
            "✅ <b>API Call Successful</b>\n\n"
            f"Status: <code>{response.status_code}</code>\n"
            f"Data: <code>{response.data}</code>"
        )
    else:
        text = (
            "❌ <b>API Call Failed</b>\n\n"
            f"Error: <code>{response.error}</code>\n"
            f"Status: <code>{response.status_code or 'N/A'}</code>"
        )

    await query.edit_message_html(text, reply_markup=build_main_keyboard())


async def _handle_example_db_query(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Example: Query database."""
    user = query.from_user
    async with get_session() as session:
        from bot.database import User, MessageLog
        from sqlalchemy import func, select

        # Get user info
        db_user = await session.get(User, user.id)

        # Count messages
        result = await session.execute(
            select(func.count(MessageLog.id)).where(MessageLog.user_id == user.id)
        )
        msg_count = result.scalar() or 0

    text = (
        "💾 <b>Database Query Result</b>\n\n"
        f"User: <b>{db_user.first_name if db_user else 'Unknown'}</b>\n"
        f"Username: @{db_user.username if db_user and db_user.username else 'N/A'}\n"
        f"Messages logged: <b>{msg_count}</b>\n"
        f"Registered: <code>{db_user.created_at.strftime('%Y-%m-%d %H:%M') if db_user else 'N/A'}</code>"
    )

    await query.edit_message_html(text, reply_markup=build_main_keyboard())


async def _handle_toggle_notifications(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle notification preference."""
    user = query.from_user
    async with get_session() as session:
        notif_key = f"notifications:{user.id}"
        current = await get_bot_state(session, notif_key)
        new_value = "false" if current != "false" else "true"
        await set_bot_state(session, notif_key, new_value)

    enabled = new_value == "true"
    await query.edit_message_html(
        f"🔔 Notifications <b>{'enabled' if enabled else 'disabled'}</b>",
        reply_markup=build_settings_keyboard(enabled),
    )


async def _handle_admin_stats(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin statistics."""
    user = query.from_user
    # Simple admin check - replace with your logic
    admin_ids = {123456789}  # Add your admin user IDs here

    if user.id not in admin_ids:
        await query.edit_message_text("⛔ Admin only")
        return

    async with get_session() as session:
        from bot.database import User, Chat, MessageLog
        from sqlalchemy import func, select

        user_count = (await session.execute(select(func.count(User.id)))).scalar() or 0
        chat_count = (await session.execute(select(func.count(Chat.id)))).scalar() or 0
        msg_count = (await session.execute(select(func.count(MessageLog.id)))).scalar() or 0

    text = (
        "📊 <b>Admin Statistics</b>\n\n"
        f"• Total Users: <b>{user_count}</b>\n"
        f"• Total Chats: <b>{chat_count}</b>\n"
        f"• Total Messages: <b>{msg_count}</b>\n"
    )

    await query.edit_message_html(text, reply_markup=build_admin_keyboard())


async def _handle_admin_broadcast(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start broadcast conversation."""
    user = query.from_user
    admin_ids = {123456789}

    if user.id not in admin_ids:
        await query.edit_message_text("⛔ Admin only")
        return

    await query.edit_message_html(
        "📢 <b>Broadcast Message</b>\n\n"
        "Send the message you want to broadcast to all users.\n"
        "Supports HTML formatting.\n\n"
        "Send /cancel to abort."
    )
    # Set conversation state
    context.user_data["broadcast_mode"] = True


async def _handle_confirmation(query, context: ContextTypes.DEFAULT_TYPE, callback_data: CallbackData) -> None:
    """Handle confirmation dialogs."""
    if callback_data.action == CallbackAction.CONFIRM_YES:
        await query.edit_message_text("✅ Confirmed!")
    else:
        await query.edit_message_text("❌ Cancelled", reply_markup=build_main_keyboard())


# === Conversation Handlers ===

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast message input."""
    if not context.user_data.get("broadcast_mode"):
        return ConversationHandler.END

    user = update.effective_user
    admin_ids = {123456789}
    if user.id not in admin_ids:
        return ConversationHandler.END

    message = update.message
    if not message:
        return WAITING_BROADCAST

    # Send confirmation
    await message.reply_html(
        f"📢 <b>Confirm Broadcast</b>\n\n"
        f"Send this message to all users?\n\n"
        f"<blockquote>{message.text_html_urled or message.text or ''}</blockquote>",
        reply_markup=build_confirmation_keyboard(
            CallbackAction.CONFIRM_YES,
            payload="broadcast",
        ),
    )

    # Store message for confirmation
    context.user_data["broadcast_message"] = {
        "text": message.text_html_urled or message.text,
        "entities": message.entities,
    }
    context.user_data["broadcast_mode"] = False

    return ConversationHandler.END


async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel broadcast."""
    context.user_data.clear()
    await update.message.reply_text("❌ Broadcast cancelled", reply_markup=build_main_keyboard())
    return ConversationHandler.END


# === Error Handler ===

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler."""
    logger.error(
        "update_error",
        error=str(context.error),
        update_type=type(update).__name__,
        exc_info=context.error,
    )

    # Try to notify user if possible
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An error occurred. The developers have been notified."
            )
        except Exception:
            pass


# === Handler Registration ===

def register_handlers(application: Application) -> None:
    """Register all handlers with the application."""
    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("stats", stats_command))

    # Messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.ALL | filters.VIDEO |
        filters.AUDIO | filters.VOICE | filters.Sticker.ALL,
        handle_media_message,
    ))

    # Callbacks
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Conversation for broadcast
    broadcast_conv = ConversationHandler(
        entry_points=[],  # Started via callback
        states={
            WAITING_BROADCAST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message),
                CommandHandler("cancel", cancel_broadcast),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_broadcast)],
        name="broadcast",
        persistent=False,
    )
    application.add_handler(broadcast_conv)

    # Error handler
    application.add_error_handler(error_handler)

    logger.info("handlers_registered")