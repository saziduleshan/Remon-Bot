import json
import logging
from datetime import datetime
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)


def _store_path() -> Path:
    return Path(config.TOKEN_DIR) / "reminders.json"


def save(chat_id: int, text: str, fire_at: datetime, name: str) -> None:
    path = _store_path()
    reminders = _load()
    reminders = [r for r in reminders if r["name"] != name]
    reminders.append({
        "chat_id": chat_id,
        "text": text,
        "fire_at": fire_at.isoformat(),
        "name": name,
    })
    _save(reminders)
    logger.debug("Saved reminder %s (fires at %s)", name, fire_at.isoformat())


def remove(name: str) -> None:
    reminders = _load()
    before = len(reminders)
    reminders = [r for r in reminders if r["name"] != name]
    if len(reminders) < before:
        _save(reminders)
        logger.debug("Removed reminder %s", name)


def load_all() -> list[dict]:
    return _load()


def _load() -> list[dict]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load reminders file")
        return []


def _save(reminders: list[dict]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(reminders, f, indent=2)
