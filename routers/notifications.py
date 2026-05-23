"""FCM token registration."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class TokenRegister(BaseModel):
    fcm_token: str


@router.post("/register-token")
async def register_token(body: TokenRegister, _: str = Depends(get_current_user)):
    db = get_db()
    result = await db.user_profile.update_one(
        {}, {"$set": {"fcm_token": body.fcm_token}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Profile not found — complete onboarding first")
    return {"status": "registered"}
