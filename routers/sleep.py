"""Sleep quality logs — hours_slept → quality auto-derived."""
from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Depends
from auth import get_current_user
from database import get_db
from models.sleep_log import SleepLogCreate, SleepQuality

router = APIRouter(prefix="/api/sleep-logs", tags=["sleep"])

_DEFAULT_THRESHOLDS = {
    "worst_max": 4.0,
    "bad_max": 6.0,
    "average_max": 7.0,
    "good_max": 8.0,
}


def _derive_quality(hours: float, thresholds: dict) -> SleepQuality:
    worst_max = thresholds.get("worst_max", 4.0)
    bad_max = thresholds.get("bad_max", 6.0)
    average_max = thresholds.get("average_max", 7.0)
    good_max = thresholds.get("good_max", 8.0)

    if hours < worst_max:
        return SleepQuality.worst
    if hours < bad_max:
        return SleepQuality.bad
    if hours < average_max:
        return SleepQuality.average
    if hours < good_max:
        return SleepQuality.good
    return SleepQuality.better


@router.post("", status_code=201)
async def log_sleep(body: SleepLogCreate, _: str = Depends(get_current_user)):
    db = get_db()
    profile = await db.user_profile.find_one({})
    raw_thresholds = (profile or {}).get("sleep_thresholds", _DEFAULT_THRESHOLDS)
    thresholds = raw_thresholds if isinstance(raw_thresholds, dict) else _DEFAULT_THRESHOLDS

    quality = _derive_quality(body.hours_slept, thresholds)

    existing = await db.sleep_logs.find_one({"date": body.date})
    if existing:
        await db.sleep_logs.update_one(
            {"date": body.date},
            {"$set": {
                "hours_slept": body.hours_slept,
                "quality": quality.value,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        existing["hours_slept"] = body.hours_slept
        existing["quality"] = quality.value
        existing["_id"] = str(existing["_id"])
        return existing

    doc = {
        "date": body.date,
        "hours_slept": body.hours_slept,
        "quality": quality.value,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.sleep_logs.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


@router.get("")
async def get_sleep_logs(days: int = 30, _: str = Depends(get_current_user)):
    db = get_db()
    query: dict = {}
    if days > 0:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        query["date"] = {"$gte": cutoff}
    docs = await db.sleep_logs.find(query).sort("date", 1).to_list(None)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"logs": docs}
