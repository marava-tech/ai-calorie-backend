"""Body analysis — trend endpoint."""
from datetime import date, timedelta
from fastapi import APIRouter, Depends
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/body-analysis", tags=["body-analysis"])


@router.get("/trend")
async def body_fat_trend(days: int = 90, user_id: str = Depends(get_current_user)):
    """Return time-series of body fat midpoint estimates from gym photo analyses."""
    db = get_db()
    match: dict = {"photos.analysis": {"$ne": None}, "user_id": user_id}
    if days > 0:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        match["date"] = {"$gte": cutoff}

    pipeline = [
        {"$match": match},
        {"$unwind": "$photos"},
        {"$match": {
            "photos.analysis": {"$ne": None},
            "photos.analysis.bf_low_pct": {"$ne": None},
            "photos.analysis.bf_high_pct": {"$ne": None},
        }},
        {"$project": {
            "_id": 0,
            "date": 1,
            "angle": "$photos.angle",
            "bf_low_pct": "$photos.analysis.bf_low_pct",
            "bf_high_pct": "$photos.analysis.bf_high_pct",
            "bf_midpoint_pct": {"$round": [
                {"$divide": [
                    {"$add": ["$photos.analysis.bf_low_pct", "$photos.analysis.bf_high_pct"]},
                    2,
                ]},
                1,
            ]},
            "caption": {"$ifNull": ["$photos.analysis.caption", ""]},
            "image_url": "$photos.image_url",
        }},
        {"$sort": {"date": 1}},
    ]

    trend = await db.gym_sessions.aggregate(pipeline).to_list(None)
    return {"trend": trend}
