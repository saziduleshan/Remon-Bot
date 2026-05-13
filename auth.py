import asyncio
import logging
import pickle
from pathlib import Path

from google.auth.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# In-memory store for pending auth flows: {chat_id: flow_state}
_pending_auth: dict[int, InstalledAppFlow] = {}


def _token_path(chat_id: int) -> Path:
    return Path(config.TOKEN_DIR) / f"{chat_id}.pickle"


def get_credentials(chat_id: int) -> Credentials | None:
    path = _token_path(chat_id)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            creds: Credentials = pickle.load(f)
    except Exception:
        return None

    if creds and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        try:
            creds.refresh(Request())
            _save(chat_id, creds)
        except Exception:
            return None

    return creds if creds and creds.valid else None


def _save(chat_id: int, creds: Credentials) -> None:
    Path(config.TOKEN_DIR).mkdir(parents=True, exist_ok=True)
    with open(_token_path(chat_id), "wb") as f:
        pickle.dump(creds, f)


def start_auth_flow(chat_id: int) -> dict | None:
    client_config = {
        "installed": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(
            client_config, SCOPES,
            redirect_uri="urn:ietf:wg:oauth:2.0:oob",
        )
        auth_url, _ = flow.authorization_url(prompt="consent")
        _pending_auth[chat_id] = flow
        return {
            "auth_url": auth_url,
            "message": (
                f"🔑 *Link Google Calendar*\n\n"
                f"1. Click this link:\n{auth_url}\n\n"
                f"2. Sign in and authorize\n"
                f"3. You'll get a code — **copy it and paste it here**\n\n"
                f"You have 5 minutes."
            ),
        }
    except Exception as e:
        logger.exception("Failed to start auth flow")
        return None


def exchange_code(chat_id: int, code: str) -> Credentials | None:
    flow = _pending_auth.pop(chat_id, None)
    if not flow:
        return None

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        _save(chat_id, creds)
        return creds
    except Exception as e:
        logger.exception("Failed to exchange auth code")
        return None


def clear_credentials(chat_id: int) -> None:
    path = _token_path(chat_id)
    if path.exists():
        path.unlink()
