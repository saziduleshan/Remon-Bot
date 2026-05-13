import json
import logging
import pickle
import time
from pathlib import Path

from google.auth.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
REDIRECT_URI = "http://127.0.0.1"


def _token_path(chat_id: int) -> Path:
    return Path(config.TOKEN_DIR) / f"{chat_id}.pickle"


def _flow_path(chat_id: int) -> Path:
    return Path(config.TOKEN_DIR) / f"flow_{chat_id}.json"


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


def _client_config() -> dict:
    return {
        "installed": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def start_auth_flow(chat_id: int) -> dict | None:
    try:
        flow = InstalledAppFlow.from_client_config(
            _client_config(), SCOPES,
            redirect_uri=REDIRECT_URI,
        )
        auth_url, state = flow.authorization_url(
            prompt="consent",
            access_type="offline",
            include_granted_scopes="false",
        )

        _save_flow(chat_id, flow)

        return {
            "auth_url": auth_url,
            "message": (
                f"🔑 *Link Google Calendar*\n\n"
                f"1. Click this link:\n`{auth_url}`\n\n"
                f"2. Sign in and authorize\n"
                f"3. Your browser will show an error page — **copy the full URL**\n"
                f"   from the address bar (it contains `?code=...`)\n"
                f"4. **Paste that URL here**\n\n"
                f"You have 5 minutes."
            ),
        }
    except Exception:
        logger.exception("Failed to start auth flow")
        return None


def _save_flow(chat_id: int, flow: InstalledAppFlow) -> None:
    Path(config.TOKEN_DIR).mkdir(parents=True, exist_ok=True)
    data = {
        "state": flow.oauth2session.state,
        "client_config": _client_config(),
        "redirect_uri": REDIRECT_URI,
        "scopes": SCOPES,
        "created_at": time.time(),
    }
    with open(_flow_path(chat_id), "w") as f:
        json.dump(data, f)
    logger.info("Saved flow state for chat %s", chat_id)


def _load_flow(chat_id: int) -> InstalledAppFlow | None:
    path = _flow_path(chat_id)
    if not path.exists():
        return None

    try:
        with open(path) as f:
            data = json.load(f)

        # Expire after 5 minutes
        if time.time() - data.get("created_at", 0) > 300:
            path.unlink()
            return None

        flow = InstalledAppFlow.from_client_config(
            data["client_config"], data["scopes"],
            redirect_uri=data["redirect_uri"],
            state=data["state"],
        )
        return flow
    except Exception:
        logger.exception("Failed to load flow")
        return None


def exchange_code(chat_id: int, url_or_code: str) -> Credentials | None:
    flow = _load_flow(chat_id)
    if not flow:
        logger.warning("No pending auth flow for chat %s", chat_id)
        return None

    _del_flow(chat_id)

    try:
        if url_or_code.startswith("http"):
            flow.fetch_token(authorization_response=url_or_code)
        else:
            flow.fetch_token(code=url_or_code)
        creds = flow.credentials
        _save(chat_id, creds)
        logger.info("Auth successful for chat %s", chat_id)
        return creds
    except Exception as e:
        logger.exception("Failed to exchange auth code for chat %s", chat_id)
        return None


def _del_flow(chat_id: int) -> None:
    path = _flow_path(chat_id)
    if path.exists():
        path.unlink()


def clear_credentials(chat_id: int) -> None:
    path = _token_path(chat_id)
    if path.exists():
        path.unlink()
    _del_flow(chat_id)
