import os
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="Authorization", auto_error=False)


def verify_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
    expected = os.environ.get("API_KEY", "")
    if not expected:
        raise HTTPException(status_code=500, detail="API_KEY not configured")
    # Accept bare key or "Bearer <key>"
    token = (api_key or "").removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return token
