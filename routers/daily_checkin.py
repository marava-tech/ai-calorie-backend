"""Daily check-in — upsert one record per user per date."""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pymongo import ReturnDocument
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
    supplement_entries: Optional[list[SupplementEntry]] = None
    if_followed: Optional[bool] = None
    gym_photo: Optional[str] = None  # "uploaded" | "skipped"


async def _sync_supplement_logs(date: str, entries: list[dict], user_id: str, db):
    """Mirror quiz supplement entries into supplement_logs so the checklist and
    correlation endpoints stay consistent with what was submitted in the quiz."""
    now = datetime.now(timezone.utc)

    async def _upsert_one(entry: dict):
        sid = entry["supplement_id"]
        if entry.get("taken"):
            await db.supplement_logs.update_one(
                {"supplement_id": sid, "date": date, "user_id": user_id},
                {
                    "$set": {
                        "supplement_name": entry["name"],
                        "units_taken": entry.get("quantity", 1),
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "supplement_id": sid,
                        "date": date,
                        "user_id": user_id,
                        "created_at": now,
                    },
                },
                upsert=True,
            )
        else:
            await db.supplement_logs.delete_one(
                {"supplement_id": sid, "date": date, "user_id": user_id}
            )

    await asyncio.gather(*[_upsert_one(e) for e in entries])


@router.post("", status_code=201)
async def upsert_checkin(body: CheckinCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    data = {k: v for k, v in body.model_dump().items() if k != "date" and v is not None}
    now = datetime.now(timezone.utc)

    doc = await db.daily_checkins.find_one_and_update(
        {"date": body.date, "user_id": user_id},
        {"$set": {**data, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    if body.supplement_entries:
        entries = [e.model_dump() for e in body.supplement_entries]
        await _sync_supplement_logs(body.date, entries, user_id, db)

    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
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
