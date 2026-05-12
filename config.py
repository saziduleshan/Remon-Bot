import os
from dataclasses import dataclass, field


@dataclass
class _Config:
    TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]
    GOOGLE_CLIENT_ID: str = os.environ["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET: str = os.environ["GOOGLE_CLIENT_SECRET"]
    TOKEN_DIR: str = os.environ.get("TOKEN_DIR", "./tokens")
    POLL_INTERVAL_MINUTES: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
    GEMINI_API_KEY: str | None = os.environ.get("GEMINI_API_KEY")
    LEAD_TIME_OPTIONS: list[int] = field(default_factory=lambda: [15, 30, 60])
    DEFAULT_LEAD_TIME_MINUTES: int = 30


config = _Config()
