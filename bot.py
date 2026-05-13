import re
from datetime import datetime, timedelta, timezone

import dateparser
from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from auth import start_auth_flow, exchange_code, get_credentials, clear_credentials
from calendar_api import (
    get_today_events,
    get_next_event,
    get_week_events,
    list_events_for_date,
    add_event,
    delete_event,
    format_event,
)
from config import config
from nlu import parse_intent

# Conversation states for /addevent
TITLE, DATETIME_STATE, DURATION, CONFIRM = range(4)


def register(application):
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("today", cmd_today))
    application.add_handler(CommandHandler("next", cmd_next))
    application.add_handler(CommandHandler("week", cmd_week))
    application.add_handler(CommandHandler("remind", cmd_remind))
    application.add_handler(CommandHandler("settings", cmd_settings))
    application.add_handler(CommandHandler("setlead", cmd_setlead))
    application.add_handler(CommandHandler("list", cmd_list))
    application.add_handler(CommandHandler("del", cmd_del))
    application.add_handler(CommandHandler(["help", "commands"], cmd_help))

    conv = ConversationHandler(
        entry_points=[CommandHandler("addevent", addevent_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addevent_title)],
            DATETIME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addevent_datetime)],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, addevent_duration)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, addevent_confirm)],
        },
        fallbacks=[CommandHandler("cancel", addevent_cancel)],
        conversation_timeout=300,
    )
    application.add_handler(conv)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_language))

    return application


# ── /start ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    creds = get_credentials(chat_id)
    if creds:
        await update.message.reply_text("✅ Already linked to Google Calendar!")
        return

    result = start_auth_flow(chat_id)
    if not result:
        await update.message.reply_text("❌ Failed to start OAuth. Try again later.")
        return

    await update.message.reply_text(result["message"], parse_mode="Markdown")


# ── /today ──────────────────────────────────────────────────────────────────

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    result = get_today_events(chat_id)
    if isinstance(result, str):
        await update.message.reply_text(result)
        return
    if not result:
        await update.message.reply_text("📭 No events today.")
        return
    lines = ["📅 *Today's Events:*"] + [format_event(e) for e in result]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /next ───────────────────────────────────────────────────────────────────

async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    result = get_next_event(chat_id)
    if isinstance(result, str):
        await update.message.reply_text(result)
        return
    await update.message.reply_text(f"⏭ *Next:* {format_event(result)}", parse_mode="Markdown")


# ── /week ───────────────────────────────────────────────────────────────────

async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    result = get_week_events(chat_id)
    if isinstance(result, str):
        await update.message.reply_text(result)
        return
    if not result:
        await update.message.reply_text("📭 No events this week.")
        return
    lines = ["📅 *This Week:*"] + [format_event(e) for e in result]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /remind (natural language) ──────────────────────────────────────────────

_REMIND_PATTERNS = [
    re.compile(r"(?:in\s+)?(\d+(?:\.\d+)?)\s*(minutes?|mins?|m)\s+(.+)", re.I),
    re.compile(r"(?:in\s+)?(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\s+(.+)", re.I),
    re.compile(r"(?:in\s+)?(\d+)\s*(?:hours?|hrs?|h)?\s*(?:and|,)?\s*(\d+)\s*(minutes?|mins?|m)\s+(.+)", re.I),
]

_MULTI_SEP = re.compile(r"[,\s]+")


async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    creds = get_credentials(chat_id)
    if not creds:
        await update.message.reply_text("⚠️ Not authenticated. Use /start first.")
        return

    text = update.message.text[len("/remind "):].strip()
    if not text:
        await update.message.reply_text(
            "Usage:\n"
            "• `/remind 30m buy milk`\n"
            "• `/remind in 1 hour meeting`\n"
            "• `/remind 15m,2h water plants` (multiple reminders)",
            parse_mode="Markdown",
        )
        return

    # Check for multiple reminders: comma or space-separated time specs
    # e.g. "15m,2h buy milk" or "15m 2h buy milk"
    # We need to separate the time specs from the message
    # Strategy: try to match the whole string first; if fails, try splitting

    matched = False
    for pattern in _REMIND_PATTERNS:
        m = pattern.match(text)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                amount = float(groups[0])
                unit = groups[1].lower()
                reminder_text = groups[2]
                delay_minutes = int(amount * 60) if unit.startswith("h") else int(amount)
                _schedule_reminder(context, chat_id, delay_minutes, reminder_text)
                unit_label = "h" if unit.startswith("h") else "m"
                await update.message.reply_text(
                    f"✅ Reminder set for {amount}{unit_label}: {reminder_text}"
                )
                matched = True
                break
            elif len(groups) == 4:
                hours = int(groups[0])
                minutes = int(groups[1])
                reminder_text = groups[3]
                delay_minutes = hours * 60 + minutes
                _schedule_reminder(context, chat_id, delay_minutes, reminder_text)
                await update.message.reply_text(
                    f"✅ Reminder set for {hours}h {minutes}m: {reminder_text}"
                )
                matched = True
                break

    if matched:
        return

    # Try parsing as a natural language datetime for absolute reminders
    # e.g. "/remind tomorrow at 3pm doctor"
    parsed = dateparser.parse(text, settings={
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": "UTC",
        "TO_TIMEZONE": "UTC",
        "RETURN_AS_TIMEZONE_AWARE": True,
    })
    if parsed:
        now = datetime.now(parsed.tzinfo or timezone.utc)
        delay = (parsed - now).total_seconds()
        if delay > 0:
            _schedule_reminder(context, chat_id, int(delay // 60), text)
            await update.message.reply_text(
                f"✅ Reminder set for {parsed.strftime('%a, %b %d at %I:%M %p')}"
            )
            return

    await update.message.reply_text(
        "❌ Couldn't parse that. Try:\n"
        "• `/remind 30m buy milk`\n"
        "• `/remind in 1 hour meeting`\n"
        "• `/remind tomorrow at 3pm doctor`",
        parse_mode="Markdown",
    )


def _schedule_reminder(context, chat_id: int, delay_minutes: int, text: str) -> None:
    job_name = f"remind_{chat_id}"
    context.job_queue.run_once(
        _send_reminder,
        when=delay_minutes * 60,
        data={"chat_id": chat_id, "text": f"⏰ Reminder: {text}"},
        name=job_name,
    )


async def _send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    await context.bot.send_message(
        chat_id=job.data["chat_id"],
        text=job.data["text"],
    )


# ── /settings + /setlead (multiple lead times) ─────────────────────────────

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    settings = context.bot_data.setdefault("settings", {})
    user_settings = settings.setdefault(str(chat_id), {})
    lead_times = user_settings.get("lead_times", [config.DEFAULT_LEAD_TIME_MINUTES])
    current = ", ".join(f"{m} min" for m in sorted(lead_times))
    await update.message.reply_text(
        f"⚙️ *Settings*\n\n"
        f"Proactive reminders: {current} before events\n\n"
        f"To change, send:\n`/setlead 15,30` (one or more, comma-separated)\n"
        f"Options: {', '.join(str(m) for m in config.LEAD_TIME_OPTIONS)}",
        parse_mode="Markdown",
    )


async def cmd_setlead(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    creds = get_credentials(chat_id)
    if not creds:
        await update.message.reply_text("⚠️ Not authenticated. Use /start first.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setlead 15,30")
        return

    raw = "".join(context.args)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    minutes_list = []
    for p in parts:
        try:
            m = int(p)
        except ValueError:
            await update.message.reply_text(f"❌ Invalid number: `{p}`", parse_mode="Markdown")
            return
        if m not in config.LEAD_TIME_OPTIONS:
            opts = ", ".join(str(o) for o in config.LEAD_TIME_OPTIONS)
            await update.message.reply_text(
                f"❌ `{m}` not valid. Options: {opts}", parse_mode="Markdown"
            )
            return
        minutes_list.append(m)

    context.bot_data.setdefault("settings", {})
    context.bot_data["settings"][str(chat_id)] = {"lead_times": minutes_list}
    display = ", ".join(f"{m} min" for m in sorted(minutes_list))
    await update.message.reply_text(f"✅ Proactive reminders set to: {display} before events")


# ── /list [date] ────────────────────────────────────────────────────────────

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    creds = get_credentials(chat_id)
    if not creds:
        await update.message.reply_text("⚠️ Not authenticated. Use /start first.")
        return

    if context.args:
        date_str = " ".join(context.args)
        dt = dateparser.parse(date_str, settings={
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "UTC",
            "TO_TIMEZONE": "UTC",
            "RETURN_AS_TIMEZONE_AWARE": True,
        })
        if not dt:
            await update.message.reply_text(
                "❌ Couldn't understand that date. Try:\n"
                "• `tomorrow`\n"
                "• `next Monday`\n"
                "• `2026-05-20`",
                parse_mode="Markdown",
            )
            return
    else:
        dt = datetime.now(timezone.utc)

    result = list_events_for_date(chat_id, dt)
    if isinstance(result, str):
        await update.message.reply_text(result)
        return

    day_label = dt.strftime("%A, %B %d")
    if not result:
        await update.message.reply_text(f"📭 No events on {day_label}.")
        return

    lines = [f"📅 *{day_label}:*"] + [format_event(e) for e in result]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /del [N] ────────────────────────────────────────────────────────────────

async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    creds = get_credentials(chat_id)
    if not creds:
        await update.message.reply_text("⚠️ Not authenticated. Use /start first.")
        return

    if context.args:
        try:
            idx = int(context.args[0]) - 1
        except ValueError:
            await update.message.reply_text("Usage: `/del N` where N is the event number")
            return

        events = context.user_data.get("del_events", [])
        if idx < 0 or idx >= len(events):
            await update.message.reply_text("❌ Invalid number. Run `/del` to see the list.")
            return

        event = events[idx]
        summary = event.get("summary", "(no title)")
        result = delete_event(chat_id, event["id"])
        if result is None:
            del context.user_data["del_events"]
            await update.message.reply_text(f"✅ Deleted: {summary}")
        else:
            await update.message.reply_text(result)
        return

    now = datetime.now(timezone.utc)
    future = now.replace(hour=23, minute=59, second=59)
    result = list_events_for_date(chat_id, now)
    combined = result if isinstance(result, list) else []

    for day_offset in range(1, 8):
        day = now + timedelta(days=day_offset)
        r = list_events_for_date(chat_id, day)
        if isinstance(r, list):
            combined.extend(r)

    if combined:
        context.user_data["del_events"] = combined[:20]
        lines = ["📋 *Select event to delete:*\n"]
        for i, ev in enumerate(combined[:20], 1):
            lines.append(f"{i}. {format_event(ev)}")
        lines.append("\nReply with: `/del N`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text("📭 No upcoming events to delete.")


# ── /addevent (conversation) ────────────────────────────────────────────────

async def addevent_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    creds = get_credentials(chat_id)
    if not creds:
        await update.message.reply_text("⚠️ Not authenticated. Use /start first.")
        return ConversationHandler.END
    await update.message.reply_text("📝 What's the event title?")
    return TITLE


async def addevent_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["ev_title"] = update.message.text.strip()
    await update.message.reply_text(
        "📅 When?\n\n"
        "Try: `tomorrow at 3pm`, `2026-05-20 14:00`, `next Monday 10am`",
        parse_mode="Markdown",
    )
    return DATETIME_STATE


async def addevent_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    dt = dateparser.parse(text, settings={
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": "UTC",
        "TO_TIMEZONE": "UTC",
        "RETURN_AS_TIMEZONE_AWARE": True,
    })
    if not dt:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d")
                dt = dt.replace(hour=12, minute=0)
            except ValueError:
                await update.message.reply_text(
                    "❌ Couldn't understand. Try:\n"
                    "• `tomorrow at 3pm`\n"
                    "• `2026-05-20 14:00`\n"
                    "• `next Monday 10am`",
                    parse_mode="Markdown",
                )
                return DATETIME_STATE

    tz = dt.tzinfo or timezone.utc
    if dt < datetime.now(tz):
        await update.message.reply_text("❌ That time is in the past! Try a future time.")
        return DATETIME_STATE

    context.user_data["ev_dt"] = dt
    await update.message.reply_text(
        f"📅 {dt.strftime('%A, %b %d at %I:%M %p')}\n"
        f"⏳ Duration in minutes? (default `60`, or `0` for all-day)",
        parse_mode="Markdown",
    )
    return DURATION


async def addevent_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        duration = max(0, int(text))
    except ValueError:
        duration = 60

    context.user_data["ev_duration"] = duration
    title = context.user_data["ev_title"]
    dt = context.user_data["ev_dt"]
    dur_str = "All day" if duration == 0 else f"{duration} min"

    await update.message.reply_text(
        f"📋 *Confirm event:*\n"
        f"• Title: {title}\n"
        f"• When: {dt.strftime('%a, %b %d at %I:%M %p')}\n"
        f"• Duration: {dur_str}\n\n"
        f"Send ✅ to confirm or ❌ to cancel",
        parse_mode="Markdown",
    )
    return CONFIRM


async def addevent_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if "✅" in text or text.lower() in ("confirm", "yes", "y", "yeah"):
        chat_id = update.effective_chat.id
        title = context.user_data["ev_title"]
        dt = context.user_data["ev_dt"]
        duration = context.user_data.get("ev_duration", 60)
        result = add_event(chat_id, title, dt, duration)
        if isinstance(result, str):
            await update.message.reply_text(result)
        else:
            await update.message.reply_text(
                f"✅ *Event created!*\n{title} — {dt.strftime('%a, %b %d at %I:%M %p')}",
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text("❌ Cancelled.")

    context.user_data.clear()
    return ConversationHandler.END


async def addevent_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


# ── /help /commands ───────────────────────────────────────────────────────

_HELP_TEXT = (
    "🤖 *Remon — Calendar Bot*\n\n"
    "Send me natural language like:\n"
    "• `what's on today`\n"
    "• `add dentist tomorrow at 2pm`\n"
    "• `remind me in 30 minutes to call mom`\n"
    "• `delete my 3pm meeting`\n\n"
    "Or use commands:\n"
    "/start — Link Google Calendar\n"
    "/today — Events today\n"
    "/next — Next event\n"
    "/week — This week\n"
    "/list [date] — Events on any date\n"
    "/addevent — Add event (guided)\n"
    "/del — Delete event\n"
    "/remind — Set reminder\n"
    "/settings — Configure proactive reminders\n"
    "/help — Show this message"
)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")


# ── Natural Language Handler ──────────────────────────────────────────────

async def handle_natural_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text:
        return

    chat_id = update.effective_chat.id

    # Detect OAuth callback URL (state may be ?state= or &state=)
    if "&code=" in text and "state=" in text:
        creds = exchange_code(chat_id, text)
        if creds:
            await update.message.reply_text("✅ Google Calendar linked successfully!")
        else:
            await update.message.reply_text("❌ Invalid code. Try /start again.")
        return

    parsed = parse_intent(text)
    if not parsed:
        await update.message.reply_text(
            "I didn't understand that. Try:\n"
            "• `what's on today`\n"
            "• `add dentist tomorrow at 2pm`\n"
            "• `remind me in 30 minutes to call mom`\n"
            "• `delete my 3pm meeting`\n"
            "• or use /help for all commands",
            parse_mode="Markdown",
        )
        return

    intent = parsed["intent"]
    entities = parsed["entities"]

    if intent == "list_today":
        await cmd_today(update, context)

    elif intent == "list_next":
        await cmd_next(update, context)

    elif intent == "list_week":
        await cmd_week(update, context)

    elif intent == "list_date":
        dt = entities.get("datetime") or datetime.now(timezone.utc)
        result = list_events_for_date(chat_id, dt)
        if isinstance(result, str):
            await update.message.reply_text(result)
        elif not result:
            await update.message.reply_text(f"📭 No events on {dt.strftime('%A, %b %d')}.")
        else:
            lines = [f"📅 *{dt.strftime('%A, %B %d')}:*"] + [format_event(e) for e in result]
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif intent == "add_event":
        title = entities.get("title", "Event")
        dt = entities.get("datetime")
        duration = entities.get("duration", 60)
        if dt is None:
            await update.message.reply_text(
                "I found you want to add an event but couldn't figure out the time. Try `/addevent`.",
                parse_mode="Markdown",
            )
            return
        result = add_event(chat_id, title, dt, duration)
        if isinstance(result, str):
            await update.message.reply_text(result)
        else:
            await update.message.reply_text(
                f"✅ *Event created!*\n{title} — {dt.strftime('%a, %b %d at %I:%M %p')}",
                parse_mode="Markdown",
            )

    elif intent == "delete_event":
        if "index" in entities:
            context.args = [str(entities["index"])]
            await cmd_del(update, context)
        elif "query" in entities:
            await update.message.reply_text(
                f"🔍 Looking for \"{entities['query']}\"... Run `/del` to see your events, "
                f"then use `/del N` to delete one.",
                parse_mode="Markdown",
            )
        else:
            await cmd_del(update, context)

    elif intent == "remind":
        delay = entities.get("delay_minutes")
        msg = entities.get("text", text)
        if delay and delay > 0:
            _schedule_reminder(context, chat_id, delay, msg)
            await update.message.reply_text(
                f"✅ Reminder set for {delay} minutes: {msg}"
            )
        else:
            await update.message.reply_text(
                "I couldn't figure out the time. Try:\n`remind me to buy milk in 30 minutes`",
                parse_mode="Markdown",
            )

    elif intent in ("settings",):
        await cmd_settings(update, context)

    elif intent == "help":
        await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")
