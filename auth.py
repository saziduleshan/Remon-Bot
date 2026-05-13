import asyncio
import pickle
from pathlib import Path

import httpx
from google.oauth2.credentials import Credentials

from config import config

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# In-memory store for pending device flows: {chat_id: device_code}
_pending_flows: dict[int, str] = {}


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


async def start_device_flow(chat_id: int) -> dict | None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/device/code",
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "scope": " ".join(SCOPES),
            },
        )
    if resp.status_code != 200:
        import logging
        logging.getLogger(__name__).error(
            "Device code request failed: %s %s", resp.status_code, resp.text
        )
        return None

    data = resp.json()
    _pending_flows[chat_id] = data["device_code"]
    return {
        "verification_url": data["verification_url"],
        "user_code": data["user_code"],
        "interval": data.get("interval", 5),
    }


async def poll_device_flow(chat_id: int) -> Credentials | None:
    device_code = _pending_flows.pop(chat_id, None)
    if not device_code:
        return None

    interval = 5
    for _ in range(60):
        await asyncio.sleep(interval)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config.GOOGLE_CLIENT_ID,
                    "client_secret": config.GOOGLE_CLIENT_SECRET,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        token_data = resp.json()
        if "access_token" in token_data:
            creds = Credentials(
                token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=config.GOOGLE_CLIENT_ID,
                client_secret=config.GOOGLE_CLIENT_SECRET,
            )
            _save(chat_id, creds)
            return creds
        error = token_data.get("error")
        if error == "slow_down":
            interval += 5
        elif error == "expired_token":
            break
        elif error == "access_denied":
            break
    return None


def clear_credentials(chat_id: int) -> None:
    path = _token_path(chat_id)
    if path.exists():
        path.unlink()
