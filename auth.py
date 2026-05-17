import json
import logging
import pickle
import secrets
import urllib.parse
from pathlib import Path

from google.auth.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
REDIRECT_URI = "http://127.0.0.1"


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


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
        code_verifier = _generate_code_verifier()

        flow = InstalledAppFlow.from_client_config(
            _client_config(), SCOPES,
            redirect_uri=REDIRECT_URI,
        )
        auth_url, _ = flow.authorization_url(
            prompt="consent",
            access_type="offline",
            code_verifier=code_verifier,
        )

        state = flow.state

        Path(config.TOKEN_DIR).mkdir(parents=True, exist_ok=True)
        with open(_flow_path(chat_id), "w") as f:
            json.dump({"state": state, "code_verifier": code_verifier}, f)

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
    except Exception as e:
        logger.exception("Failed to start auth flow")
        return {"error": str(e)}


def exchange_code(chat_id: int, url_or_code: str) -> Credentials | None:
    try:
        flow_path = _flow_path(chat_id)
        if not flow_path.exists():
            logger.warning("No saved flow for chat %s", chat_id)
            return None

        with open(flow_path) as f:
            saved = json.load(f)

        flow_path.unlink()

        flow = InstalledAppFlow.from_client_config(
            _client_config(), SCOPES,
            redirect_uri=REDIRECT_URI,
            state=saved["state"],
        )
        try:
            flow.code_verifier = saved["code_verifier"]
        except AttributeError:
            pass
        flow.oauth2session.code_verifier = saved["code_verifier"]

        if url_or_code.startswith("http"):
            flow.fetch_token(authorization_response=url_or_code)
        else:
            flow.fetch_token(code=url_or_code)

        creds = flow.credentials
        _save(chat_id, creds)
        logger.info("Auth successful for chat %s", chat_id)
        return creds
    except Exception:
        logger.exception("Failed to exchange auth code for chat %s", chat_id)
        return None


def clear_credentials(chat_id: int) -> None:
    for path in (_token_path(chat_id), _flow_path(chat_id)):
        if path.exists():
            path.unlink()
