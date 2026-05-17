import os
from dataclasses import dataclass, field


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}\n"
            f"Set it in your deployment dashboard or .env file."
        )
    return val


@dataclass
class _Config:
    TELEGRAM_TOKEN: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    TOKEN_DIR: str = ""
    POLL_INTERVAL_MINUTES: int = 5
    GEMINI_API_KEY: str | None = None
    LEAD_TIME_OPTIONS: list[int] = field(default_factory=lambda: [15, 30, 60])
    DEFAULT_LEAD_TIME_MINUTES: int = 30


config = _Config()
config.TELEGRAM_TOKEN = _require_env("TELEGRAM_TOKEN")
config.GOOGLE_CLIENT_ID = _require_env("GOOGLE_CLIENT_ID")
config.GOOGLE_CLIENT_SECRET = _require_env("GOOGLE_CLIENT_SECRET")
config.TOKEN_DIR = os.environ.get("TOKEN_DIR", "./tokens")
config.POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
config.GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
