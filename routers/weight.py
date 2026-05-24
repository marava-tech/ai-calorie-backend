"""Weight logs + TDEE recalculation on save."""
import logging
from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Depends
from auth import get_current_user
from database import get_db
from models.weight_log import WeightLogCreate
from services.tdee import calculate_tdee
from services.fcm import send_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/weight-logs", tags=["weight"])


@router.post("", status_code=201)
async def log_weight(body: WeightLogCreate, _: str = Depends(get_current_user)):
    db = get_db()
    doc = {
        "date": body.date,
        "weight_kg": body.weight_kg,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.weight_logs.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    # Recalculate TDEE using new weight
    profile = await db.user_profile.find_one({})
    if profile:
        old_goal = profile.get("goal_kcal", 0)
        tdee = calculate_tdee(body.weight_kg, profile["height_cm"], profile["age"], profile["sex"])
        await db.user_profile.update_one(
            {}, {"$set": {**tdee, "weight_kg": body.weight_kg}}
        )
        if abs(tdee["goal_kcal"] - old_goal) > 50 and profile.get("fcm_token"):
            try:
                await send_notification(
                    profile["fcm_token"],
                    "Daily goal updated",
                    f"New weight {body.weight_kg}kg → {tdee['goal_kcal']} kcal/day",
                )
            except Exception as e:
                logger.error("Failed to send weight update FCM: %s", e)

    return doc


@router.get("")
async def get_weight_logs(days: int = 90, _: str = Depends(get_current_user)):
    db = get_db()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    docs = await db.weight_logs.find(
        {"date": {"$gte": cutoff}}
    ).sort("date", 1).to_list(None)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"logs": docs}
