import os
from dataclasses import dataclass, field


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

    def load(self):
        self.TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
        self.GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
        self.GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.TOKEN_DIR = os.environ.get("TOKEN_DIR", "./tokens")
        self.POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
        self.GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

    def validate(self):
        missing = []
        if not self.TELEGRAM_TOKEN:
            missing.append("TELEGRAM_TOKEN")
        if not self.GOOGLE_CLIENT_ID:
            missing.append("GOOGLE_CLIENT_ID")
        if not self.GOOGLE_CLIENT_SECRET:
            missing.append("GOOGLE_CLIENT_SECRET")
        if missing:
            raise RuntimeError(
                f"Missing required environment variable(s): {', '.join(missing)}\n"
                f"Set them in your Northflank dashboard under Environment."
            )


config = _Config()
