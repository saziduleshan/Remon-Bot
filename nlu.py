import json
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import dateparser

from config import config

logger = logging.getLogger(__name__)

# ── Gemini setup (optional, lazy) ─────────────────────────────────────────

_gemini_client = None
_gemini_initialized = False


def _get_gemini():
    global _gemini_client, _gemini_initialized
    if _gemini_initialized:
        return _gemini_client
    _gemini_initialized = True
    if not config.GEMINI_API_KEY:
        return None
    try:
        from google import genai
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
        logger.info("Gemini NLU initialized")
    except Exception:
        logger.warning("Failed to initialize Gemini — falling back to patterns only")
    return _gemini_client


# ── Pattern definitions ───────────────────────────────────────────────────

_ACTION_WORDS = r"(?:add|create|schedule|set\s*up|book|make|put|new\s+event|plan|note\s+down|i\s+need\s+to)"
_DELETE_WORDS = r"(?:delete|remove|cancel|erase|get\s+rid\s+of|nuke|kill|strip|drop|clear)"
_REMIND_WORDS = r"(?:remind|set\s+(?:a\s+)?reminder|reminder|wake\s+me|ping\s+me|heads\s+up)"
_DAY_NAMES = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"

_INTENT_PATTERNS: list[tuple[str, re.Pattern]] = []


def _p(intent: str, pattern: str) -> tuple[str, re.Pattern]:
    return (intent, re.compile(pattern, re.I))


def _compile_patterns():
    if _INTENT_PATTERNS:
        return

    _INTENT_PATTERNS.extend([

        # ── help / greeting ────────────────────────────────────────────
        _p("help", r"^(hi|hello|hey|yo|sup|good\s+(morning|afternoon|evening)|howdy)\s*$"),
        _p("help", r"^(help|commands|what\s+can\s+you\s+do|how\s+do\s+you\s+work)\s*$"),
        _p("help", r"^(what\s+(are\s+)?(your\s+)?commands|show\s+commands|command\s+list)\s*$"),

        # ── list_today ─────────────────────────────────────────────────
        _p("list_today", r"(what'?s|what\s+is|show|list|view|tell\s+me).*(today|my\s+calendar|my\s+schedule)"),
        _p("list_today", r"^(today|today'?s\s+(events|schedule|calendar|plan|agenda))\s*$"),
        _p("list_today", r"events?\s+(for\s+)?today"),
        _p("list_today", r"schedule\s+(for\s+)?today"),
        _p("list_today", r"what(\'s| is)\s+(on\s+|up\s+)?today"),
        _p("list_today", r"(do\s+i\s+have|got|am\s+i)\s+(anything\s+)?today"),
        _p("list_today", r"today'?s\s+(schedule|events|calendar|plan|agenda)"),
        _p("list_today", r"what(\'s| is)\s+(happening|going\s+on)\s+today"),
        _p("list_today", r"(show|what'?s)\s+(me\s+)?my\s+(day|schedule|calendar)\s*(for\s+)?today"),
        _p("list_today", r"what\s+(am\s+i|do\s+i)\s+doing\s+today"),

        # ── list_next ──────────────────────────────────────────────────
        _p("list_next", r"(what'?s|show|view|list|tell\s+me).*(next|coming\s+up|upcoming)"),
        _p("list_next", r"^(next|upcoming|coming\s+up)\s*$"),
        _p("list_next", r"(what'?s\s+)?(next|upcoming|coming\s+up)\s+(event|thing|meeting|one)"),
        _p("list_next", r"what(\'s| is)\s+(after|next)"),
        _p("list_next", r"anything\s+(else\s+)?(after\s+)?(today\s+)?"),
        _p("list_next", r"what(\'s| is)\s+on\s+(deck|the\s+horizon|the\s+calendar)\s*(next)?"),

        # ── list_week ──────────────────────────────────────────────────
        _p("list_week", r"(this\s+)?week(\s+ahead|\s+plan|\s+schedule|\s+calendar)?"),
        _p("list_week", r"(what'?s|show|view|list|tell\s+me).*(week|7\s+days)"),
        _p("list_week", r"weekly\s+(schedule|events|calendar|plan|agenda)"),
        _p("list_week", r"schedule\s+(for\s+)?(this\s+)?week"),
        _p("list_week", r"this\s+(week'?s\s+)?(events|schedule|calendar|plan|agenda)"),
        _p("list_week", r"what(\'s| is)\s+(happening|going\s+on)\s+(this\s+)?week"),
        _p("list_week", r"what\s+(am\s+i|do\s+i)\s+doing\s+(this\s+)?week"),
        _p("list_week", r"what(\'s| is)\s+(my\s+)?(schedule|plan|agenda)\s+(for\s+)?(this\s+)?week"),
        _p("list_week", r"anything\s+(happening|going\s+on)\s+(this\s+)?week"),

        # ── list_date ──────────────────────────────────────────────────
        _p("list_date", rf"(what'?s|what\s+is|show|view|list|tell\s+me)\s+(on|for)\s+(tomorrow|{_DAY_NAMES})"),
        _p("list_date", rf"(what'?s|what\s+is|show|view|list|tell\s+me)\s+(on|for)\s+(next\s+{_DAY_NAMES})"),
        _p("list_date", r"(what'?s|what\s+is|show|view|list|tell\s+me)\s+(on|for)\s+(\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?)"),
        _p("list_date", r"(what'?s|what\s+is|show|view|list|tell\s+me)\s+(on|for)\s+(.+?)(?:\s*$)"),
        _p("list_date", rf"(schedule|events|calendar|meetings|agenda)\s+(?:for|on)\s+(tomorrow|{_DAY_NAMES})"),
        _p("list_date", rf"(schedule|events|calendar|meetings|agenda)\s+(?:for|on)\s+(next\s+{_DAY_NAMES})"),
        _p("list_date", r"^(tomorrow|day\s+after\s+tomorrow)\s*$"),
        _p("list_date", r"what\s+(am\s+i|do\s+i)\s+doing\s+(on\s+)?(.+)"),
        _p("list_date", r"(am\s+i|are\s+we)\s+(free|busy)\s+(on\s+)?(.+)"),
        _p("list_date", r"anything\s+(on|for)\s+(.+)"),

        # ── add_event ──────────────────────────────────────────────────
        _p("add_event", rf"^{_ACTION_WORDS}\s+(?:a\s+|an\s+|the\s+|an?\s+event\s+)?(.+)"),
        _p("add_event", r"^(put|add)\s+(.+?)\s+(on|in|to)\s+(my\s+)?calendar\s+(.+)"),
        _p("add_event", r"^(make|book|schedule)\s+(?:an?\s+)?(appointment|meeting)\s+(?:for\s+)?(.+)"),
        _p("add_event", r"^(schedule|plan)\s+(.+?)\s+(?:for|on)\s+(.+)"),

        # ── delete_event ───────────────────────────────────────────────
        _p("delete_event", rf"^{_DELETE_WORDS}\s+(?:the\s+)?(.+)"),
        _p("delete_event", r"i\s+(want\s+to\s+)?(delete|remove|cancel)\s+(?:the\s+)?(.+)"),
        _p("delete_event", r"can\s+(you\s+)?(delete|remove|cancel)\s+(?:the\s+)?(.+)"),
        _p("delete_event", r"get\s+rid\s+of\s+(?:the\s+)?(.+)"),

        # ── remind ─────────────────────────────────────────────────────
        _p("remind", rf"^{_REMIND_WORDS}\s+(me\s+)?(.+)"),
        _p("remind", r"can\s+(you\s+)?remind\s+(me\s+)?(.+)"),
        _p("remind", r"set\s+(?:a\s+|an\s+)?(?:countdown\s+)?(?:timer|reminder|alarm)\s+(?:for\s+)?(.+)"),
        _p("remind", r"remind\s+(me\s+)?(?:in|after)\s+(.+)"),
        _p("remind", r"wake\s+me\s+up\s+(?:in\s+)?(.+)"),
        _p("remind", r"ping\s+me\s+(?:in\s+)?(.+)"),
        _p("remind", r"(give\s+me|send)\s+(?:a\s+)?heads?\s*up\s+(?:in\s+)?(.+)"),
        _p("remind", r"don'?t\s+let\s+me\s+forget\s+(?:to\s+)?(.+)"),
        _p("remind", r"nudge\s+me\s+(?:in\s+)?(.+)"),
        _p("remind", r"remind\s+(me\s+)?about\s+(.+)"),
        _p("remind", r"remind\s+(me\s+)?(?:to\s+|that\s+)(.+)"),

        # ── settings ───────────────────────────────────────────────────
        _p("settings", r"^(settings|preferences|configuration|setup)\s*$"),
        _p("settings", r"(change|update|set|show|view|configure)\s+(my\s+)?(settings|preferences|lead\s*time|reminder)"),
        _p("settings", r"(how\s+many|when)\s+(reminders|notifications)\s+(do\s+i\s+get|should\s+i\s+get)"),
        _p("settings", r"i\s+want\s+(more|fewer|different)\s+(reminders|notifications)"),

    ])


# ── Public API ─────────────────────────────────────────────────────────────

def _needs_gemini_fallback(result: dict) -> bool:
    """Pattern matched but missing critical entities — let Gemini try."""
    intent = result["intent"]
    entities = result["entities"]
    if intent == "add_event" and entities.get("datetime") is None:
        return True
    if intent == "remind" and entities.get("delay_minutes") is None and entities.get("datetime") is None:
        return True
    return False


def parse_intent(text: str) -> dict | None:
    """Try pattern matching first, then Gemini fallback."""

    # Step 1: patterns
    result = _parse_with_patterns(text)
    if result and not _needs_gemini_fallback(result):
        return result

    # Step 2: Gemini fallback (either patterns didn't match, or entities are incomplete)
    gemini = _get_gemini()
    if gemini is not None:
        try:
            gemini_result = _parse_with_gemini(text)
            if gemini_result and gemini_result.get("intent", "unknown") != "unknown":
                return gemini_result
        except Exception:
            logger.exception("Gemini parse failed")

    return result


# ── Pattern matching ───────────────────────────────────────────────────────

def _parse_with_patterns(text: str) -> dict | None:
    _compile_patterns()
    text_stripped = text.strip()
    if not text_stripped:
        return None

    for intent, pattern in _INTENT_PATTERNS:
        m = pattern.search(text_stripped)
        if m:
            entities = _extract_entities(intent, text_stripped, m)
            return {"intent": intent, "entities": entities}

    return None


def _extract_entities(intent: str, text: str, match: re.Match) -> dict:
    entities: dict = {}

    if intent == "add_event":
        raw = match.group(match.lastindex) if match.lastindex else text
        parsed = _parse_add_event_details(raw)
        if parsed:
            entities.update(parsed)

    elif intent == "delete_event":
        raw = match.group(match.lastindex) if match.lastindex else text
        idx = _extract_number(raw)
        if idx is not None:
            entities["index"] = idx
        else:
            entities["query"] = raw.strip()

    elif intent == "remind":
        raw = match.group(match.lastindex) if match.lastindex else text
        parsed = _parse_remind_details(raw)
        if parsed:
            entities.update(parsed)

    elif intent == "list_date":
        date_portion = match.group(match.lastindex) if match.lastindex else text
        dt = _extract_date(date_portion)
        if not dt:
            dt = _extract_date(text)
        if dt:
            entities["datetime"] = dt

    return entities


# ── Gemini parsing ─────────────────────────────────────────────────────────

_GEMINI_SYSTEM = (
    "You are a calendar bot intent parser. "
    "Classify messages into these intents: help, list_today, list_next, list_week, "
    "list_date, add_event, delete_event, remind, settings, unknown. "
    "For add_event: title (string), datetime (ISO 8601 with timezone), duration (int minutes, default 60). "
    "For remind: delay_minutes (int minutes from now) OR datetime (ISO 8601 with timezone), text (string). "
    "For delete_event: index (int or null), query (string). "
    "For list_date: datetime (ISO 8601 with timezone, default noon if no time). "
    "Return ONLY valid JSON with fields: intent, entities."
)

_GEMINI_PROMPT = (
    "You are a calendar bot intent parser. "
    "Classify the user's message into one of these intents and return ONLY valid JSON:\n"
    "Intents: help, list_today, list_next, list_week, list_date, add_event, delete_event, remind, settings, unknown\n\n"
    "Rules:\n"
    "- add_event: {\"intent\": \"add_event\", \"entities\": {\"title\": \"...\", \"datetime\": \"ISO 8601 with timezone offset\", \"duration\": 60}}\n"
    "- remind: {\"intent\": \"remind\", \"entities\": {\"delay_minutes\": 30, \"text\": \"...\"}}\n"
    "- delete_event: {\"intent\": \"delete_event\", \"entities\": {\"index\": null, \"query\": \"...\"}}\n"
    "- list_date: {\"intent\": \"list_date\", \"entities\": {\"datetime\": \"ISO 8601\"}}\n"
    "- others: {\"intent\": \"...\", \"entities\": {}}\n"
    "- If unclear: {\"intent\": \"unknown\", \"entities\": {}}\n\n"
    "Message: {text}"
)


def _parse_with_gemini(text: str) -> dict | None:
    response = _gemini_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"{_GEMINI_SYSTEM}\n\n{_GEMINI_PROMPT.format(text=text)}",
        config={"response_mime_type": "application/json"},
    )
    raw = response.text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    data = json.loads(raw)
    intent = data.get("intent", "").strip()
    entities = data.get("entities", {})

    # Convert ISO datetime strings to datetime objects
    if entities.get("datetime") and isinstance(entities["datetime"], str):
        try:
            dt = datetime.fromisoformat(entities["datetime"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(config.TIMEZONE))
            entities["datetime"] = dt
        except ValueError:
            del entities["datetime"]

    if intent not in ("help", "list_today", "list_next", "list_week",
                       "list_date", "add_event", "delete_event", "remind", "settings"):
        return {"intent": "unknown", "entities": {}}

    return {"intent": intent, "entities": entities}


# ── Entity helpers ─────────────────────────────────────────────────────────

def _extract_number(text: str) -> int | None:
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    words = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
             "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
    for word, num in words.items():
        if word in text.lower():
            return num
    return None


def _extract_date(text: str) -> datetime | None:
    return dateparser.parse(text, settings={
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": config.TIMEZONE,
        "TO_TIMEZONE": config.TIMEZONE,
        "RETURN_AS_TIMEZONE_AWARE": True,
    })


def _parse_add_event_details(text: str) -> dict | None:
    duration = 60
    text_clean = text.strip()

    dur_m = re.search(
        r"(?:for\s+|lasting\s+|duration\s+)?(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)\s*(?:long)?",
        text_clean, re.I,
    )
    if dur_m:
        amount = int(dur_m.group(1))
        unit = dur_m.group(2).lower()
        duration = amount * 60 if unit.startswith("h") else amount
        text_clean = text_clean[:dur_m.start()] + text_clean[dur_m.end():]

    dt = dateparser.parse(text_clean, settings={
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": config.TIMEZONE,
        "TO_TIMEZONE": config.TIMEZONE,
        "RETURN_AS_TIMEZONE_AWARE": True,
    })
    if dt:
        title = _extract_add_title(text_clean, dt)
        return {"title": title or "Event", "datetime": dt, "duration": duration}

    return None


def _extract_add_title(full_text: str, dt: datetime) -> str:
    text_lower = full_text.lower().strip()
    search_text = full_text.strip()

    date_prefixes = [
        r"\bon\b", r"\bat\b", r"\bfor\b", r"\bfrom\b",
        r"\bthis\b", r"\bnext\b",
    ]
    for day in ["monday", "tuesday", "wednesday", "thursday", "friday",
                 "saturday", "sunday", "today", "tomorrow"]:
        date_prefixes.append(rf"\b{day}\b")

    positions = []
    for pat_str in date_prefixes:
        for m in re.finditer(pat_str, search_text, re.I):
            positions.append(m.start())
        if pat_str in [r"\bon\b", r"\bat\b", r"\bfor\b"]:
            for m in re.finditer(pat_str, search_text.lower(), re.I):
                if m.start() > 0:
                    positions.append(m.start() - 1)

    if positions:
        split_pos = min(positions)
        candidate = full_text[:split_pos].strip().rstrip(",").strip()
        if candidate:
            return candidate

    cleaned = re.sub(r"\d{1,2}:\d{2}\s*(?:am|pm)?", "", full_text, flags=re.I)
    cleaned = re.sub(r"\d{4}[/-]\d{2}[/-]\d{2}", "", cleaned)
    for day in ["monday", "tuesday", "wednesday", "thursday", "friday",
                 "saturday", "sunday", "today", "tomorrow", "yesterday"]:
        cleaned = re.sub(rf"\s*\b{day}\b\s*", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:at|on|for|this|next|from)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "Event"


def _parse_remind_details(text: str) -> dict | None:
    dur_m = re.search(
        r"(?:in|after)\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|m|hours?|hrs?|h)",
        text, re.I,
    )
    if dur_m:
        amount = float(dur_m.group(1))
        unit = dur_m.group(2).lower()
        delay_minutes = int(amount * 60) if unit.startswith("h") else int(amount)
        msg_text = text[:dur_m.start()] + text[dur_m.end():]
        msg_text = re.sub(r"^(to|about)\s+", "", msg_text, flags=re.I).strip()
        return {"delay_minutes": delay_minutes, "text": msg_text or "Reminder"}

    simple_m = re.match(r"(\d+)\s*(m|h|min|hour)\s+(.+)", text, re.I)
    if simple_m:
        amount = int(simple_m.group(1))
        unit = simple_m.group(2).lower()
        delay_minutes = amount * 60 if unit in ("h", "hour") else amount
        return {"delay_minutes": delay_minutes, "text": simple_m.group(3).strip()}

    parsed = dateparser.parse(text, settings={
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": config.TIMEZONE,
        "TO_TIMEZONE": config.TIMEZONE,
        "RETURN_AS_TIMEZONE_AWARE": True,
    })
    if parsed:
        now = datetime.now(parsed.tzinfo or timezone.utc)
        delay = (parsed - now).total_seconds()
        if delay > 0:
            return {"delay_minutes": int(delay // 60), "text": text}

    return None
