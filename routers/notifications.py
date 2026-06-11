"""FCM token registration."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import get_current_user
from database import get_db
from services import fcm as fcm_svc

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class TokenRegister(BaseModel):
    fcm_token: str


@router.post("/register-token")
async def register_token(body: TokenRegister, user_id: str = Depends(get_current_user)):
    db = get_db()
    result = await db.user_profile.update_one(
        {"user_id": user_id}, {"$set": {"fcm_token": body.fcm_token}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Profile not found — complete onboarding first")
    return {"status": "registered"}


@router.post("/test")
async def send_test_notification(user_id: str = Depends(get_current_user)):
    db = get_db()
    profile_doc = await db.user_profile.find_one({"user_id": user_id})
    if not profile_doc:
        raise HTTPException(404, "Profile not found")
    fcm_token = profile_doc.get("fcm_token")
    if not fcm_token:
        raise HTTPException(400, "No FCM token registered — open the app first")
    result = await fcm_svc.send_notification(
        fcm_token,
        "Test Notification",
        "Fitness OS notifications are working!",
    )
    return {"status": "sent", "fcm_response": result}
