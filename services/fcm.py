"""Firebase Cloud Messaging — send push notifications via HTTP v1 API."""
import asyncio
import os
import json
import httpx
import google.auth.transport.requests
from google.oauth2 import service_account


_credentials = None


def _get_credentials():
    global _credentials
    if _credentials is None:
        creds_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "/app/firebase-credentials.json")
        _credentials = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
    return _credentials


def _refresh_credentials_sync():
    """Synchronous credential refresh — must be called via run_in_executor."""
    creds = _get_credentials()
    request = google.auth.transport.requests.Request()
    creds.refresh(request)
    return creds.token


async def send_notification(fcm_token: str, title: str, body: str, data: dict | None = None):
    """Send FCM push notification to a device token."""
    # Credential refresh is synchronous (network I/O via google-auth) — run in thread
    # to avoid blocking the async event loop, which would silently kill APScheduler jobs.
    loop = asyncio.get_event_loop()
    token = await loop.run_in_executor(None, _refresh_credentials_sync)

    project_id = os.environ["FIREBASE_PROJECT_ID"]
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    message: dict = {
        "message": {
            "token": fcm_token,
            "notification": {"title": title, "body": body},
        }
    }
    if data:
        message["message"]["data"] = {k: str(v) for k, v in data.items()}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(message),
        )
        resp.raise_for_status()
        return resp.json()
