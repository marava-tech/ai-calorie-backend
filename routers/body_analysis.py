"""Body analysis — trend endpoint."""
from fastapi import APIRouter, Depends
from auth import verify_api_key
from database import get_db

router = APIRouter(prefix="/api/body-analysis", tags=["body-analysis"])


@router.get("/trend")
async def body_fat_trend(_: str = Depends(verify_api_key)):
    """Return time-series of body fat midpoint estimates from gym photo analyses."""
    db = get_db()
    sessions = await db.gym_sessions.find(
        {"photos.analysis": {"$ne": None}}, {"date": 1, "photos": 1}
    ).sort("date", 1).to_list(None)

    trend = []
    for session in sessions:
        for photo in session.get("photos", []):
            analysis = photo.get("analysis")
            if not analysis:
                continue
            low = analysis.get("bf_low_pct")
            high = analysis.get("bf_high_pct")
            if low is not None and high is not None:
                midpoint = round((low + high) / 2, 1)
                trend.append({
                    "date": session["date"],
                    "angle": photo.get("angle"),
                    "bf_midpoint_pct": midpoint,
                    "bf_low_pct": low,
                    "bf_high_pct": high,
                    "caption": analysis.get("caption", ""),
                })

    return {"trend": trend}
