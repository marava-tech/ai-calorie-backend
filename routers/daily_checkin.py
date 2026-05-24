"""Daily check-in — upsert one record per user per date."""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/daily-checkin", tags=["daily-checkin"])


class CheckinCreate(BaseModel):
    date: str  # YYYY-MM-DD
    gym: Optional[bool] = None
    workout_type: Optional[str] = None
    fish_oil: Optional[bool] = None
    fish_oil_caps: Optional[int] = None
    magnesium: Optional[bool] = None
    magnesium_caps: Optional[int] = None
    vitamin_d3: Optional[bool] = None
    vitamin_d3_caps: Optional[int] = None
    multi_vitamin: Optional[bool] = None
    multi_vitamin_caps: Optional[int] = None
    whey_protein: Optional[bool] = None
    whey_protein_scoops: Optional[int] = None
    # Dynamic supplement tracking — key: supplement_id, value: {taken: bool, units: int}
    supplement_data: Optional[dict[str, Any]] = None
    if_followed: Optional[bool] = None
    gym_photo: Optional[str] = None  # "uploaded" | "skipped"


@router.post("", status_code=201)
async def upsert_checkin(body: CheckinCreate, _: str = Depends(get_current_user)):
    db = get_db()
    data = {k: v for k, v in body.model_dump().items() if k != "date" and v is not None}
    now = datetime.now(timezone.utc)

    existing = await db.daily_checkins.find_one({"date": body.date})
    if existing:
        await db.daily_checkins.update_one(
            {"date": body.date},
            {"$set": {**data, "updated_at": now}},
        )
        doc = await db.daily_checkins.find_one({"date": body.date})
        doc["id"] = str(doc.pop("_id"))
        return doc

    doc = {"date": body.date, **data, "created_at": now, "updated_at": now}
    result = await db.daily_checkins.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("")
async def get_checkin(date: str, _: str = Depends(get_current_user)):
    db = get_db()
    doc = await db.daily_checkins.find_one({"date": date})
    if not doc:
        raise HTTPException(404, "No check-in found for this date")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/history")
async def checkin_history(
    skip: int = 0, limit: int = 30, _: str = Depends(get_current_user)
):
    db = get_db()
    docs = await db.daily_checkins.find({}).sort("date", -1).skip(skip).limit(limit).to_list(None)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs
