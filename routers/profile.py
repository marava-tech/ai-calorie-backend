"""User profile — create, read, update + TDEE calculation."""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone

from auth import get_current_user
from database import get_db
from models.profile import ProfileCreate, ProfilePatch
from services.tdee import calculate_tdee
from services.fcm import send_notification

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _tdee_dict(doc: dict) -> dict:
    return calculate_tdee(
        doc["weight_kg"], doc["height_cm"], doc["age"], doc["sex"]
    )


@router.post("", status_code=201)
async def create_profile(body: ProfileCreate, _: str = Depends(get_current_user)):
    db = get_db()
    existing = await db.user_profile.find_one({})
    if existing:
        raise HTTPException(400, "Profile already exists — use PATCH to update")

    tdee = calculate_tdee(body.weight_kg, body.height_cm, body.age, body.sex)
    doc = {
        **body.model_dump(),
        **tdee,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "fcm_token": None,
        "streaks": {},
    }
    result = await db.user_profile.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


@router.get("")
async def get_profile(_: str = Depends(get_current_user)):
    db = get_db()
    doc = await db.user_profile.find_one({})
    if not doc:
        raise HTTPException(404, "Profile not found")
    doc["_id"] = str(doc["_id"])
    return doc


@router.patch("")
async def patch_profile(body: ProfilePatch, _: str = Depends(get_current_user)):
    db = get_db()
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No fields provided")

    # Refetch profile to recalculate TDEE if weight changes
    doc = await db.user_profile.find_one({})
    if not doc:
        raise HTTPException(404, "Profile not found")

    merged = {**doc, **update_data}
    tdee = calculate_tdee(merged["weight_kg"], merged["height_cm"], merged["age"], merged["sex"])

    # Check if goal changed significantly
    old_goal = doc.get("goal_kcal", 0)
    new_goal = tdee["goal_kcal"]
    if abs(new_goal - old_goal) > 50 and doc.get("fcm_token"):
        try:
            await send_notification(
                doc["fcm_token"],
                "Goal Updated",
                f"Your daily calorie goal changed to {new_goal} kcal",
            )
        except Exception:
            pass

    update_data.update(tdee)
    update_data["updated_at"] = datetime.now(timezone.utc)

    await db.user_profile.update_one({}, {"$set": update_data})
    updated = await db.user_profile.find_one({})
    updated["_id"] = str(updated["_id"])
    return updated
