"""Main entry point for the Telegram bot."""

from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import asynccontextmanager

from telegram.ext import Application, ApplicationBuilder, Defaults
from telegram.constants import ParseMode

from bot.config import settings
from bot.database import close_db, init_db
from bot.external_api import close_api_client
from bot.handlers import register_handlers
from bot.jobs import setup_job_queue, shutdown_job_queue
from bot.logging_config import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: Application):
    """Application lifespan manager."""
    # Startup
    logger.info("bot_starting", version="0.1.0")
    setup_logging()

    # Initialize database
    await init_db()
    logger.info("database_initialized")

    # Setup job queue
    await setup_job_queue(app)
    logger.info("job_queue_started")

    yield

    # Shutdown
    logger.info("bot_shutting_down")
    await shutdown_job_queue()
    await close_api_client()
    await close_db()
    logger.info("bot_shutdown_complete")


def create_application() -> Application:
    """Create and configure the PTB Application."""
    defaults = Defaults(
        parse_mode=ParseMode.HTML,
        disable_notification=False,
        protect_content=False,
    )

    builder = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .defaults(defaults)
        .concurrent_updates(True)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
    )

    # Build application
    application = builder.build()

    # Register handlers
    register_handlers(application)

    return application


async def _post_init(app: Application) -> None:
    """Post-initialization hook."""
    # Set bot commands for menu button
    from telegram import BotCommand

    commands = [
        BotCommand("start", "Show main menu"),
        BotCommand("help", "Show help"),
        BotCommand("ping", "Check latency"),
        BotCommand("settings", "Bot settings"),
        BotCommand("stats", "Your statistics"),
    ]
    await app.bot.set_my_commands(commands)

    # Log bot info
    me = await app.bot.get_me()
    logger.info("bot_initialized", bot_id=me.id, bot_username=me.username)


async def _post_shutdown(app: Application) -> None:
    """Post-shutdown hook."""
    pass


async def run_polling() -> None:
    """Run bot in polling mode."""
    application = create_application()

    # Setup lifespan
    async with lifespan(application):
        logger.info("starting_polling")
        await application.run_polling(
            allowed_updates=[
                "message",
                "edited_message",
                "callback_query",
                "inline_query",
                "chosen_inline_result",
            ],
            drop_pending_updates=True,
        )


async def run_webhook() -> None:
    """Run bot in webhook mode."""
    if not settings.is_webhook_mode:
        raise RuntimeError("Webhook mode not configured. Set WEBHOOK_URL in .env")

    application = create_application()

    # Setup lifespan
    async with lifespan(application):
        logger.info("starting_webhook", url=settings.webhook_url, port=settings.webhook_port)

        # Set webhook
        await application.bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.webhook_secret,
            drop_pending_updates=True,
            allowed_updates=[
                "message",
                "edited_message",
                "callback_query",
                "inline_query",
                "chosen_inline_result",
            ],
        )

        # Start webhook server
        await application.run_webhook(
            listen=settings.webhook_host,
            port=settings.webhook_port,
            secret_token=settings.webhook_secret,
            webhook_url=settings.webhook_url,
        )


def main() -> None:
    """Main entry point."""
    try:
        if settings.is_webhook_mode:
            asyncio.run(run_webhook())
        else:
            asyncio.run(run_polling())
    except KeyboardInterrupt:
        logger.info("bot_stopped_by_user")
    except Exception as e:
        logger.error("bot_fatal_error", error=str(e), exc_info=e)
        sys.exit(1)


if __name__ == "__main__":
    main()