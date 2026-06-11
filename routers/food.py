"""Food logging — AI analysis pipeline + CRUD for logs."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form

from bson import ObjectId
from typing import Optional

from auth import get_current_user
from database import get_db
from models.food_log import FoodLogCreate, FoodItem, MacroSource, MealSlot
from services import gemini as gemini_svc
from services import minio_client
from services.openfoodfacts import lookup_macros
from utils import validate_image_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/food", tags=["food"])


async def _resolve_macros(name: str, weight_g: float, api_key: str | None) -> dict:
    result = await lookup_macros(name, weight_g)
    if result:
        return result
    if not api_key:
        raise HTTPException(402, "Set your OpenRouter API key in Settings to use AI features")
    ai_result = await gemini_svc.estimate_macros(name, weight_g, api_key=api_key)
    ai_result["source"] = "ai_estimated"
    return ai_result


async def _update_if_log(food_date: str, timestamp: datetime, user_id: str, db):
    """Derive IF adherence from the eating window in user_profile."""
    profile = await db.user_profile.find_one({"user_id": user_id})
    if not profile:
        return

    window_start = profile.get("eating_window_start", "13:00")
    window_end = profile.get("eating_window_end", "21:00")
    tz_name = profile.get("user_timezone", "UTC")

    start_h, start_m = map(int, window_start.split(":"))
    end_h, end_m = map(int, window_end.split(":"))

    # Convert UTC timestamp to the user's local timezone before comparison
    try:
        user_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown user_timezone '%s', falling back to UTC", tz_name)
        user_tz = ZoneInfo("UTC")

    local_time = timestamp.astimezone(user_tz)
    food_time = local_time.hour * 60 + local_time.minute
    window_start_min = start_h * 60 + start_m
    window_end_min = end_h * 60 + end_m

    if window_start_min <= window_end_min:
        in_window = window_start_min <= food_time <= window_end_min
    else:
        # Cross-midnight window (e.g. 22:00–06:00)
        in_window = food_time >= window_start_min or food_time <= window_end_min

    existing = await db.if_logs.find_one({"date": food_date, "user_id": user_id})
    if existing:
        # If any entry is outside window, mark non-adherent
        if not in_window:
            await db.if_logs.update_one(
                {"date": food_date, "user_id": user_id}, {"$set": {"adhered": False}}
            )
    else:
        await db.if_logs.insert_one({"date": food_date, "adhered": in_window, "user_id": user_id})


@router.post("/analyze")
async def analyze_food(
    photo: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    db = get_db()
    image_bytes = await photo.read()
    validate_image_upload(image_bytes, photo.filename or "", photo.content_type)

    # Fetch user's API key
    profile = await db.user_profile.find_one({"user_id": user_id})
    api_key = (profile or {}).get("openrouter_api_key")
    if not api_key:
        raise HTTPException(402, "Set your OpenRouter API key in Settings to use AI features")

    # Upload to MinIO for storage
    filename = f"{uuid.uuid4()}.jpg"
    image_url = await minio_client.upload_image(image_bytes, minio_client.BUCKET_FOOD, filename)

    # AI food analysis
    analysis = await gemini_svc.analyze_food(image_bytes, api_key=api_key)
    items = analysis.get("items", [])
    scale_weight_g = analysis.get("scale_weight_g")

    # Saved meal similarity check — only fetch name + item names (scoped to user)
    saved_meals = await db.saved_meals.find(
        {"user_id": user_id}, {"_id": 1, "name": 1, "items.name": 1}
    ).to_list(None)
    meal_suggestion = None
    if saved_meals and items:
        detected_names = {item["name"].lower() for item in items}
        best_overlap = 0.0
        best_meal = None
        for meal in saved_meals:
            meal_names = {i["name"].lower() for i in meal.get("items", [])}
            if not meal_names:
                continue
            overlap = len(detected_names & meal_names) / max(len(meal_names), 1)
            if overlap > best_overlap:
                best_overlap = overlap
                best_meal = meal
        if best_overlap >= 0.6 and best_meal:
            meal_suggestion = {
                "meal_id": str(best_meal["_id"]),
                "meal_name": best_meal["name"],
                "overlap": round(best_overlap, 2),
            }

    # Resolve macros for all detected items in parallel
    macro_list = await asyncio.gather(*[
        _resolve_macros(item["name"], item["estimated_weight_g"], api_key) for item in items
    ])
    enriched_items = [{**item, **macros} for item, macros in zip(items, macro_list)]

    return {
        "items": enriched_items,
        "scale_weight_g": scale_weight_g,
        "image_url": image_url,
        "meal_suggestion": meal_suggestion,
    }


@router.post("/logs", status_code=201)
async def create_food_log(body: FoodLogCreate, background_tasks: BackgroundTasks, user_id: str = Depends(get_current_user)):
    db = get_db()
    now = datetime.now(timezone.utc)

    # Derive the log date in the user's local timezone so midnight-crossover entries
    # land on the correct day (e.g. 1 AM IST is still the same calendar day for the user).
    profile = await db.user_profile.find_one({"user_id": user_id})
    tz_name = (profile or {}).get("user_timezone", "UTC")
    try:
        user_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        user_tz = ZoneInfo("UTC")
    food_date = now.astimezone(user_tz).date().isoformat()

    # Fetch user's API key — only needed if OpenFoodFacts misses an item
    api_key = (profile or {}).get("openrouter_api_key")

    # Resolve macros — skip lookup for items that already carry all four macro values
    # (e.g. supplements logged from the quiz with macro_source='database').
    resolved_items = []
    total_cal = total_protein = total_carbs = total_fat = 0.0

    items_needing_lookup = [
        item for item in body.items
        if not (item.calories_kcal is not None and item.protein_g is not None
                and item.carbs_g is not None and item.fat_g is not None)
    ]
    macro_lookup_results = await asyncio.gather(*[
        _resolve_macros(item.name, item.estimated_weight_g, api_key)
        for item in items_needing_lookup
    ])
    lookup_iter = iter(macro_lookup_results)

    for item in body.items:
        resolved = item.model_dump()
        if (item.calories_kcal is not None and item.protein_g is not None
                and item.carbs_g is not None and item.fat_g is not None):
            macros = {
                "calories_kcal": item.calories_kcal,
                "protein_g": item.protein_g,
                "carbs_g": item.carbs_g,
                "fat_g": item.fat_g,
            }
        else:
            macros = next(lookup_iter)
            resolved.update(macros)
        resolved_items.append(resolved)
        total_cal += macros.get("calories_kcal", 0)
        total_protein += macros.get("protein_g", 0)
        total_carbs += macros.get("carbs_g", 0)
        total_fat += macros.get("fat_g", 0)

    doc = {
        "user_id": user_id,
        "date": food_date,
        "meal_slot": body.meal_slot,
        "items": resolved_items,
        "image_url": body.image_url,
        "note": body.note,
        "totals": {
            "calories_kcal": round(total_cal, 1),
            "protein_g": round(total_protein, 1),
            "carbs_g": round(total_carbs, 1),
            "fat_g": round(total_fat, 1),
        },
        "created_at": now,
    }

    # Supplements are submitted once per day from the daily quiz.
    # Replace any existing supplement entries for today to prevent duplicates
    # when the user re-submits the quiz.
    if body.meal_slot == MealSlot.supplement:
        await db.food_logs.delete_many({"date": food_date, "meal_slot": MealSlot.supplement.value, "user_id": user_id})

    result = await db.food_logs.insert_one(doc)

    background_tasks.add_task(_update_if_log, food_date, now, user_id, db)

    doc["_id"] = str(result.inserted_id)
    return doc


@router.delete("/logs/{log_id}", status_code=204)
async def delete_food_log(log_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    try:
        oid = ObjectId(log_id)
    except Exception:
        raise HTTPException(400, "Invalid log ID")
    result = await db.food_logs.delete_one({"_id": oid, "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Food log not found")


@router.get("/logs")
async def get_food_logs(date: str, user_id: str = Depends(get_current_user)):
    """date format: YYYY-MM-DD (query param ?date=)"""
    db = get_db()
    docs = await db.food_logs.find({"date": date, "user_id": user_id}).to_list(None)

    grouped: dict[str, list] = {"breakfast": [], "lunch": [], "dinner": [], "extras": [], "supplement": [], "meal1": [], "meal2": [], "snack": []}
    slot_totals: dict[str, dict] = {}

    for doc in docs:
        slot = doc.get("meal_slot", "snack")
        doc["_id"] = str(doc["_id"])
        grouped.setdefault(slot, []).append(doc)

    # Calculate per-slot totals
    day_total = {"calories_kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for slot, entries in grouped.items():
        t = {"calories_kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        for entry in entries:
            totals = entry.get("totals", {})
            for k in t:
                t[k] += totals.get(k, 0)
                day_total[k] += totals.get(k, 0)
        slot_totals[slot] = {k: round(v, 1) for k, v in t.items()}

    return {
        "date": date,
        "entries": grouped,
        "slot_totals": slot_totals,
        "day_total": {k: round(v, 1) for k, v in day_total.items()},
    }


@router.get("/daily-totals")
async def get_daily_totals(days: int = 30, user_id: str = Depends(get_current_user)):
    """Returns daily aggregated calories + protein for the past N days."""
    db = get_db()
    profile = await db.user_profile.find_one({"user_id": user_id})
    tz_name = (profile or {}).get("user_timezone", "UTC")
    try:
        user_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        user_tz = ZoneInfo("UTC")
    today = datetime.now(user_tz).date()
    match_stage: dict = {"user_id": user_id}
    if days > 0:
        start = (today - timedelta(days=days - 1)).isoformat()
        match_stage["date"] = {"$gte": start, "$lte": today.isoformat()}

    pipeline = [
        {"$match": match_stage},
        {"$group": {
            "_id": "$date",
            "calories_kcal": {"$sum": "$totals.calories_kcal"},
            "protein_g": {"$sum": "$totals.protein_g"},
        }},
        {"$project": {
            "_id": 0,
            "date": "$_id",
            "calories_kcal": {"$round": ["$calories_kcal", 1]},
            "protein_g": {"$round": ["$protein_g", 1]},
        }},
        {"$sort": {"date": 1}},
    ]

    result = await db.food_logs.aggregate(pipeline).to_list(None)
    return {"totals": result}
