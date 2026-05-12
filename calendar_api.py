from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from auth import get_credentials


def _build_service(chat_id: int):
    creds = get_credentials(chat_id)
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)


def _not_authed() -> str:
    return "⚠️ Not authenticated. Use /start first."


def get_today_events(chat_id: int) -> list[dict[str, Any]] | str:
    service = _build_service(chat_id)
    if not service:
        return _not_authed()

    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    events = _fetch_events(service, now.isoformat(), end_of_day.isoformat())
    return events if events else []


def get_next_event(chat_id: int) -> dict[str, Any] | str:
    service = _build_service(chat_id)
    if not service:
        return _not_authed()

    now = datetime.now(timezone.utc)
    events = _fetch_events(service, now.isoformat(), (now + timedelta(days=30)).isoformat(), max_results=1)
    if not events:
        return "📭 No upcoming events."
    return events[0]


def get_week_events(chat_id: int) -> list[dict[str, Any]] | str:
    service = _build_service(chat_id)
    if not service:
        return _not_authed()

    now = datetime.now(timezone.utc)
    end_of_week = now + timedelta(days=7)
    events = _fetch_events(service, now.isoformat(), end_of_week.isoformat())
    return events if events else []


def get_upcoming_events(chat_id: int, within_minutes: int) -> list[dict[str, Any]] | str:
    service = _build_service(chat_id)
    if not service:
        return _not_authed()

    now = datetime.now(timezone.utc)
    end = now + timedelta(minutes=within_minutes)
    events = _fetch_events(service, now.isoformat(), end.isoformat())
    return events if events else []


def list_events_for_date(chat_id: int, start_dt: datetime) -> list[dict[str, Any]] | str:
    service = _build_service(chat_id)
    if not service:
        return _not_authed()

    start = start_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end = start_dt.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
    events = _fetch_events(service, start, end)
    return events if events else []


def add_event(chat_id: int, title: str, start_dt: datetime, duration_minutes: int = 60) -> dict | str:
    service = _build_service(chat_id)
    if not service:
        return _not_authed()

    end_dt = start_dt + timedelta(minutes=duration_minutes)
    body = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
    }
    try:
        return service.events().insert(calendarId="primary", body=body).execute()
    except HttpError as e:
        return f"❌ Failed to create event: {e}"


def delete_event(chat_id: int, event_id: str) -> str | None:
    service = _build_service(chat_id)
    if not service:
        return _not_authed()

    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return None
    except HttpError as e:
        return f"❌ Failed to delete event: {e}"


def _fetch_events(
    service,
    time_min: str,
    time_max: str,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    kwargs = {
        "calendarId": "primary",
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if max_results:
        kwargs["maxResults"] = max_results
    try:
        events_result = service.events().list(**kwargs).execute()
        return events_result.get("items", [])
    except HttpError:
        return []


def format_event(event: dict[str, Any]) -> str:
    start = event["start"].get("dateTime", event["start"].get("date"))
    summary = event.get("summary", "(no title)")
    start_dt = datetime.fromisoformat(start)
    time_str = start_dt.strftime("%I:%M %p").lstrip("0")
    return f"• {time_str} — {summary}"
