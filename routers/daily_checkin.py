"""Daily check-in — upsert one record per user per date."""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/daily-checkin", tags=["daily-checkin"])


class SupplementEntry(BaseModel):
    supplement_id: str
    name: str
    taken: bool
    quantity: float
    unit: str


class CheckinCreate(BaseModel):
    date: str  # YYYY-MM-DD
    gym: Optional[bool] = None
    workout_type: Optional[str] = None
    supplement_entries: Optional[list[SupplementEntry]] = None  # replaces all hardcoded supplement fields
    if_followed: Optional[bool] = None
    gym_photo: Optional[str] = None  # "uploaded" | "skipped"


@router.post("", status_code=201)
async def upsert_checkin(body: CheckinCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    data = {k: v for k, v in body.model_dump().items() if k != "date" and v is not None}
    # Serialize supplement_entries as list of dicts
    if "supplement_entries" in data and data["supplement_entries"] is not None:
        data["supplement_entries"] = [
            e if isinstance(e, dict) else e for e in data["supplement_entries"]
        ]
    now = datetime.now(timezone.utc)

    existing = await db.daily_checkins.find_one({"date": body.date, "user_id": user_id})
    if existing:
        await db.daily_checkins.update_one(
            {"date": body.date, "user_id": user_id},
            {"$set": {**data, "updated_at": now}},
        )
        doc = await db.daily_checkins.find_one({"date": body.date, "user_id": user_id})
        doc["id"] = str(doc.pop("_id"))
        return doc

    doc = {"date": body.date, "user_id": user_id, **data, "created_at": now, "updated_at": now}
    result = await db.daily_checkins.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("")
async def get_checkin(date: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    doc = await db.daily_checkins.find_one({"date": date, "user_id": user_id})
    if not doc:
        raise HTTPException(404, "No check-in found for this date")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/history")
async def checkin_history(
    skip: int = 0, limit: int = 30, user_id: str = Depends(get_current_user)
):
    db = get_db()
    docs = await db.daily_checkins.find({"user_id": user_id}).sort("date", -1).skip(skip).limit(limit).to_list(None)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs
