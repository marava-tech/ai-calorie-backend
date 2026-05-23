"""Firebase Cloud Messaging — send push notifications via HTTP v1 API."""
import os
import json
import httpx
import google.auth
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


async def send_notification(fcm_token: str, title: str, body: str, data: dict | None = None):
    """Send FCM push notification to a device token."""
    creds = _get_credentials()
    request = google.auth.transport.requests.Request()
    creds.refresh(request)

    project_id = os.environ["FIREBASE_PROJECT_ID"]
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    message = {
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
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            content=json.dumps(message),
        )
        resp.raise_for_status()
        return resp.json()
