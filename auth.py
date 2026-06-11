"""JWT authentication — OTP-based email auth + get_current_user dependency."""
import os
from datetime import datetime, timezone

from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

_jwt_secret = os.environ.get("JWT_SECRET")
if not _jwt_secret:
    raise RuntimeError("JWT_SECRET environment variable is not set")
SECRET_KEY = _jwt_secret
ALGORITHM = "HS256"

# JWT_EXPIRATION in milliseconds (default 15 days)
_expiration_ms = int(os.environ.get("JWT_EXPIRATION", 1296000000))
_expiration_s = _expiration_ms // 1000

bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: str) -> str:
    exp = int(datetime.now(timezone.utc).timestamp()) + _expiration_s
    return jwt.encode({"sub": user_id, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
