import random
import string
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId

from database import get_db
from auth import create_access_token, get_current_user
from models.user import SendOtpRequest, VerifyOtpRequest, Token, UsernameUpdate
from services.email_service import send_otp as send_otp_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

_OTP_TTL_MINUTES = 5


def _generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


@router.post("/send-otp", status_code=200)
async def send_otp(body: SendOtpRequest):
    """Send OTP to email. Creates user if first time."""
    db = get_db()
    email = body.email.lower()

    otp = _generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_OTP_TTL_MINUTES)

    await db.otp_requests.delete_many({"email": email})
    await db.otp_requests.insert_one({
        "email": email,
        "otp": otp,
        "expires_at": expires_at,
        "created_at": datetime.now(timezone.utc),
    })

    await send_otp_email(email, otp)
    return {"message": "OTP sent"}


@router.post("/verify-otp", response_model=Token)
async def verify_otp(body: VerifyOtpRequest):
    """Verify OTP and return JWT. Creates user on first login."""
    db = get_db()
    email = body.email.lower()
    otp = body.otp.strip()

    record = await db.otp_requests.find_one({"email": email})
    if not record:
        raise HTTPException(status_code=400, detail="No OTP found — please request a new one")

    if datetime.now(timezone.utc) > record["expires_at"].replace(tzinfo=timezone.utc):
        await db.otp_requests.delete_many({"email": email})
        raise HTTPException(status_code=400, detail="OTP expired — please request a new one")

    if record["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    await db.otp_requests.delete_many({"email": email})

    existing = await db.users.find_one({"email": email})
    is_new = existing is None

    if is_new:
        result = await db.users.insert_one({
            "email": email,
            "username": email.split("@")[0],
            "created_at": datetime.now(timezone.utc),
        })
        user_id = str(result.inserted_id)
    else:
        user_id = str(existing["_id"])

    return Token(
        access_token=create_access_token(user_id),
        is_new_user=is_new,
    )


@router.get("/me")
async def get_me(user_id: str = Depends(get_current_user)):
    db = get_db()
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": user.get("username", ""), "email": user.get("email", "")}


@router.patch("/username", status_code=200)
async def update_username(body: UsernameUpdate, user_id: str = Depends(get_current_user)):
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=422, detail="Username must be at least 3 characters")
    if " " in username:
        raise HTTPException(status_code=422, detail="Username cannot contain spaces")

    db = get_db()
    existing = await db.users.find_one({"username": username, "_id": {"$ne": ObjectId(user_id)}})
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"username": username}})
    return {"username": username}
