"""Weekly summary aggregation."""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/summary", tags=["summary"])


def _week_dates(week_str: str) -> tuple[str, str]:
    """Parse YYYY-WW and return (monday_date, sunday_date) as YYYY-MM-DD strings."""
    year, week = map(int, week_str.split("-W"))
    monday = date.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


@router.get("/weekly")
async def weekly_summary(week: str, _: str = Depends(get_current_user)):
    """week format: YYYY-WN (e.g. 2026-W21)"""
    try:
        # Normalize: "YYYY-WW" or "YYYY-WN"
        if "-W" not in week:
            raise ValueError
        start_date, end_date = _week_dates(week)
    except Exception:
        raise HTTPException(400, "Invalid week format. Use YYYY-WN (e.g. 2026-W21)")

    db = get_db()
    date_filter = {"date": {"$gte": start_date, "$lte": end_date}}

    # Food logs
    food_logs = await db.food_logs.find(date_filter).to_list(None)
    days_logged = len({l["date"] for l in food_logs})
    avg_cal = avg_protein = avg_carbs = avg_fat = 0.0
    if food_logs:
        days_with_food = {l["date"] for l in food_logs}
        day_totals: dict[str, dict] = {}
        for log in food_logs:
            d = log["date"]
            if d not in day_totals:
                day_totals[d] = {"cal": 0, "protein": 0, "carbs": 0, "fat": 0}
            t = log.get("totals", {})
            day_totals[d]["cal"] += t.get("calories_kcal", 0)
            day_totals[d]["protein"] += t.get("protein_g", 0)
            day_totals[d]["carbs"] += t.get("carbs_g", 0)
            day_totals[d]["fat"] += t.get("fat_g", 0)
        n = len(day_totals)
        avg_cal = round(sum(v["cal"] for v in day_totals.values()) / n, 1)
        avg_protein = round(sum(v["protein"] for v in day_totals.values()) / n, 1)
        avg_carbs = round(sum(v["carbs"] for v in day_totals.values()) / n, 1)
        avg_fat = round(sum(v["fat"] for v in day_totals.values()) / n, 1)

    # Gym sessions
    gym_sessions = await db.gym_sessions.find({**date_filter, "attended": True}).to_list(None)
    gym_days = len(gym_sessions)

    # IF adherence
    if_logs = await db.if_logs.find(date_filter).to_list(None)
    if_adhered = sum(1 for l in if_logs if l.get("adhered", False))
    if_total = len(if_logs)

    # Sleep breakdown
    sleep_logs = await db.sleep_logs.find(date_filter).to_list(None)
    sleep_breakdown = {}
    for log in sleep_logs:
        q = log.get("quality", "unknown")
        sleep_breakdown[q] = sleep_breakdown.get(q, 0) + 1

    # Weight delta
    weight_logs = await db.weight_logs.find(date_filter).sort("date", 1).to_list(None)
    weight_delta = None
    if len(weight_logs) >= 2:
        weight_delta = round(weight_logs[-1]["weight_kg"] - weight_logs[0]["weight_kg"], 2)

    # Best meal photo (highest calorie entry with image)
    best_photo = None
    for log in sorted(food_logs, key=lambda l: l.get("totals", {}).get("calories_kcal", 0), reverse=True):
        if log.get("image_url"):
            best_photo = log["image_url"]
            break

    profile = await db.user_profile.find_one({})
    goal_kcal = profile.get("goal_kcal", 0) if profile else 0

    return {
        "week": week,
        "start_date": start_date,
        "end_date": end_date,
        "nutrition": {
            "avg_calories_kcal": avg_cal,
            "avg_protein_g": avg_protein,
            "avg_carbs_g": avg_carbs,
            "avg_fat_g": avg_fat,
            "goal_kcal": goal_kcal,
            "days_logged": days_logged,
        },
        "gym": {"sessions": gym_days},
        "intermittent_fasting": {"adhered_days": if_adhered, "total_logged_days": if_total},
        "sleep": {"breakdown": sleep_breakdown, "days_logged": len(sleep_logs)},
        "weight_delta_kg": weight_delta,
        "best_meal_photo_url": best_photo,
    }
