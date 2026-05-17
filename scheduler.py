import logging
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.ext import Application

from auth import get_credentials
from calendar_api import get_upcoming_events, format_event
from config import config

logger = logging.getLogger(__name__)


async def poll_user(chat_id: int, bot: Bot, lead_times: list[int]) -> None:
    creds = get_credentials(chat_id)
    if not creds:
        return

    for lead_time in lead_times:
        events = get_upcoming_events(chat_id, lead_time)
        if isinstance(events, str) or not events:
            continue

        for event in events:
            start_str = event["start"].get("dateTime", event["start"].get("date"))
            start_dt = datetime.fromisoformat(start_str)
            now = datetime.now(timezone.utc)
            delta = (start_dt - now).total_seconds()
            if 0 <= delta <= lead_time * 60:
                text = f"⏰ *Reminder:* {format_event(event)} (in {lead_time} min)"
                try:
                    await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
                except Exception:
                    logger.exception("Failed to send reminder to %s", chat_id)


async def poll_all(application: Application) -> None:
    bot = application.bot
    settings = application.bot_data.setdefault("settings", {})

    # Auto-register any authenticated user who hasn't configured settings
    token_dir = Path(config.TOKEN_DIR)
    if token_dir.exists():
        for p in token_dir.glob("*.pickle"):
            chat_id_str = p.stem
            if chat_id_str not in settings and chat_id_str.lstrip("-").isdigit():
                settings[chat_id_str] = {"lead_times": [config.DEFAULT_LEAD_TIME_MINUTES]}
                logger.info("Auto-registered user %s for proactive reminders", chat_id_str)

    for chat_id_str, user_settings in settings.items():
        chat_id = int(chat_id_str)
        lead_times = user_settings.get("lead_times", [config.DEFAULT_LEAD_TIME_MINUTES])
        try:
            await poll_user(chat_id, bot, lead_times)
        except Exception:
            logger.exception("Error polling user %s", chat_id)


def start_scheduler(application: Application) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_all,
        "interval",
        minutes=config.POLL_INTERVAL_MINUTES,
        args=[application],
        id="poll_calendars",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — polling every %d minutes", config.POLL_INTERVAL_MINUTES)
    return scheduler
