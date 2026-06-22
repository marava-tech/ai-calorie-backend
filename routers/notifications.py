"""FCM token registration."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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


@router.post("/test-daily-summary")
async def send_test_daily_summary(user_id: str = Depends(get_current_user)):
    """Trigger today's log summary notification immediately (for testing)."""
    db = get_db()
    profile_doc = await db.user_profile.find_one({"user_id": user_id})
    if not profile_doc:
        raise HTTPException(404, "Profile not found")
    fcm_token = profile_doc.get("fcm_token")
    if not fcm_token:
        raise HTTPException(400, "No FCM token registered — open the app first")

    tz_name = profile_doc.get("user_timezone", "UTC")
    try:
        user_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        user_tz = ZoneInfo("UTC")

    today = datetime.now(user_tz).date().isoformat()

    pipeline = [
        {"$match": {"user_id": user_id, "date": today}},
        {"$group": {
            "_id": None,
            "total_kcal": {"$sum": "$totals.calories_kcal"},
            "total_protein": {"$sum": "$totals.protein_g"},
            "meal_count": {"$sum": 1},
        }},
    ]
    totals_docs = await db.food_logs.aggregate(pipeline).to_list(1)
    totals = totals_docs[0] if totals_docs else {}

    total_kcal = round(totals.get("total_kcal", 0))
    total_protein = round(totals.get("total_protein", 0))
    meal_count = totals.get("meal_count", 0)
    goal_kcal = profile_doc.get("goal_kcal") or 0

    if meal_count == 0:
        notif_body = "No meals logged yet today — don't forget to track your food!"
    else:
        remaining = goal_kcal - total_kcal if goal_kcal else 0
        remaining_str = (
            f"{abs(remaining)} kcal {'over' if remaining < 0 else 'remaining'}"
            if goal_kcal else f"{total_kcal} kcal logged"
        )
        notif_body = (
            f"{total_kcal} kcal · {total_protein}g protein · "
            f"{meal_count} meal{'s' if meal_count != 1 else ''} — {remaining_str}"
        )

    result = await fcm_svc.send_notification(
        fcm_token,
        "Today's Log Summary",
        notif_body,
        {"type": "daily_quiz", "date": today},
    )
    return {
        "status": "sent",
        "notification_body": notif_body,
        "totals": {"kcal": total_kcal, "protein_g": total_protein, "meals": meal_count},
        "fcm_response": result,
    }
