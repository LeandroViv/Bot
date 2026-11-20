"""Scheduled jobs using APScheduler and PTB JobQueue."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application, JobQueue

from bot.config import settings
from bot.database import get_session, get_bot_state, set_bot_state
from bot.external_api import get_api_client
from bot.logging_config import get_logger

logger = get_logger(__name__)

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the APScheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
    return _scheduler


async def setup_job_queue(application: Application) -> None:
    """Setup PTB JobQueue and APScheduler jobs."""
    job_queue: JobQueue = application.job_queue
    scheduler = get_scheduler()

    # === PTB JobQueue Jobs (run within bot context) ===

    # Daily cleanup at 3 AM
    job_queue.run_daily(
        callback=daily_cleanup_job,
        time=dt.time(3, 0, tzinfo=dt.timezone.utc),
        name="daily_cleanup",
    )

    # Hourly stats logging
    job_queue.run_repeating(
        callback=hourly_stats_job,
        interval=dt.timedelta(hours=1),
        first=dt.timedelta(minutes=1),
        name="hourly_stats",
    )

    # === APScheduler Jobs (more flexible scheduling) ===

    # External API health check every 5 minutes
    scheduler.add_job(
        external_api_health_check,
        trigger=IntervalTrigger(minutes=5),
        id="api_health_check",
        name="External API Health Check",
        replace_existing=True,
    )

    # Daily user engagement summary at 9 AM
    scheduler.add_job(
        daily_engagement_summary,
        trigger=CronTrigger(hour=9, minute=0, timezone=settings.scheduler_timezone),
        id="daily_engagement",
        name="Daily Engagement Summary",
        replace_existing=True,
    )

    # Weekly database maintenance on Sunday 4 AM
    scheduler.add_job(
        weekly_db_maintenance,
        trigger=CronTrigger(day_of_week="sun", hour=4, minute=0, timezone=settings.scheduler_timezone),
        id="weekly_db_maintenance",
        name="Weekly DB Maintenance",
        replace_existing=True,
    )

    # Start scheduler
    scheduler.start()
    logger.info("job_queue_setup_complete")


async def shutdown_job_queue() -> None:
    """Shutdown job queue and scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
    logger.info("job_queue_shutdown_complete")


# === Job Implementations ===

async def daily_cleanup_job(context) -> None:
    """Daily cleanup job - runs via PTB JobQueue."""
    logger.info("daily_cleanup_started")

    try:
        # Example: Clean old message logs (older than 30 days)
        async with get_session() as session:
            from bot.database import MessageLog
            from sqlalchemy import delete

            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
            result = await session.execute(
                delete(MessageLog).where(MessageLog.created_at < cutoff)
            )
            deleted = result.rowcount

        logger.info("daily_cleanup_completed", deleted_logs=deleted)

    except Exception as e:
        logger.error("daily_cleanup_failed", error=str(e), exc_info=e)


async def hourly_stats_job(context) -> None:
    """Hourly statistics logging job."""
    try:
        async with get_session() as session:
            from bot.database import User, Chat, MessageLog
            from sqlalchemy import func, select

            # Count totals
            users = (await session.execute(select(func.count(User.id)))).scalar() or 0
            chats = (await session.execute(select(func.count(Chat.id)))).scalar() or 0
            messages = (await session.execute(select(func.count(MessageLog.id)))).scalar() or 0

            # Messages in last hour
            hour_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
            recent = (await session.execute(
                select(func.count(MessageLog.id)).where(MessageLog.created_at >= hour_ago)
            )).scalar() or 0

        logger.info(
            "hourly_stats",
            total_users=users,
            total_chats=chats,
            total_messages=messages,
            messages_last_hour=recent,
        )

        # Store in bot state for /stats command
        async with get_session() as session:
            await set_bot_state(session, "stats:last_hourly", str({
                "users": users,
                "chats": chats,
                "messages": messages,
                "recent": recent,
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            }))

    except Exception as e:
        logger.error("hourly_stats_failed", error=str(e), exc_info=e)


async def external_api_health_check() -> None:
    """Check external API health - runs via APScheduler."""
    logger.debug("api_health_check_started")

    try:
        client = get_api_client()
        response = await client.health_check()

        status = "healthy" if response.success else "unhealthy"
        logger.info("api_health_check_completed", status=status, status_code=response.status_code)

        # Store status
        async with get_session() as session:
            await set_bot_state(session, "external_api:status", status)
            await set_bot_state(session, "external_api:last_check", dt.datetime.now(dt.timezone.utc).isoformat())

    except Exception as e:
        logger.error("api_health_check_failed", error=str(e), exc_info=e)
        async with get_session() as session:
            await set_bot_state(session, "external_api:status", "error")


async def daily_engagement_summary() -> None:
    """Generate daily engagement summary - runs via APScheduler."""
    logger.info("daily_engagement_started")

    try:
        async with get_session() as session:
            from bot.database import User, MessageLog
            from sqlalchemy import func, select

            yesterday = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
            day_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + dt.timedelta(days=1)

            # Active users yesterday
            active_users = (await session.execute(
                select(func.count(func.distinct(MessageLog.user_id)))
                .where(MessageLog.created_at >= day_start)
                .where(MessageLog.created_at < day_end)
            )).scalar() or 0

            # New users yesterday
            new_users = (await session.execute(
                select(func.count(User.id))
                .where(User.created_at >= day_start)
                .where(User.created_at < day_end)
            )).scalar() or 0

            # Messages yesterday
            messages = (await session.execute(
                select(func.count(MessageLog.id))
                .where(MessageLog.created_at >= day_start)
                .where(MessageLog.created_at < day_end)
            )).scalar() or 0

        summary = {
            "date": yesterday.date().isoformat(),
            "active_users": active_users,
            "new_users": new_users,
            "messages": messages,
        }

        logger.info("daily_engagement_completed", **summary)

        # Store for admin dashboard
        async with get_session() as session:
            await set_bot_state(session, f"engagement:{yesterday.date().isoformat()}", str(summary))

    except Exception as e:
        logger.error("daily_engagement_failed", error=str(e), exc_info=e)


async def weekly_db_maintenance() -> None:
    """Weekly database maintenance - runs via APScheduler."""
    logger.info("weekly_db_maintenance_started")

    try:
        # For SQLite, we can run VACUUM to reclaim space
        async with get_session() as session:
            await session.execute("VACUUM")

        logger.info("weekly_db_maintenance_completed")

    except Exception as e:
        logger.error("weekly_db_maintenance_failed", error=str(e), exc_info=e)


# === Utility Functions for Manual Job Triggering ===

async def trigger_job_now(job_name: str) -> bool:
    """Manually trigger a job by name."""
    scheduler = get_scheduler()
    job = scheduler.get_job(job_name)
    if job:
        scheduler.add_job(job.func, trigger="date", run_date=dt.datetime.now(dt.timezone.utc))
        logger.info("job_triggered_manually", job_name=job_name)
        return True
    return False


async def get_job_status() -> dict:
    """Get status of all scheduled jobs."""
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return {"jobs": jobs}