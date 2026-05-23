"""Sleep quality logs."""
from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from auth import get_current_user
from database import get_db
from models.sleep_log import SleepLogCreate

router = APIRouter(prefix="/api/sleep-logs", tags=["sleep"])


@router.post("", status_code=201)
async def log_sleep(body: SleepLogCreate, _: str = Depends(get_current_user)):
    db = get_db()
    # Upsert — one log per date
    existing = await db.sleep_logs.find_one({"date": body.date})
    if existing:
        await db.sleep_logs.update_one(
            {"date": body.date},
            {"$set": {"quality": body.quality, "updated_at": datetime.now(timezone.utc)}},
        )
        existing["quality"] = body.quality
        existing["_id"] = str(existing["_id"])
        return existing

    doc = {
        "date": body.date,
        "quality": body.quality,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.sleep_logs.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


@router.get("")
async def get_sleep_logs(days: int = 30, _: str = Depends(get_current_user)):
    db = get_db()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    docs = await db.sleep_logs.find(
        {"date": {"$gte": cutoff}}
    ).sort("date", 1).to_list(None)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"logs": docs}
