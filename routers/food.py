"""Food logging — AI analysis pipeline + CRUD for logs."""
import logging
import uuid
import base64
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
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


async def _resolve_macros(name: str, weight_g: float) -> dict:
    result = await lookup_macros(name, weight_g)
    if result:
        return result
    # Fallback to Gemini
    ai_result = await gemini_svc.estimate_macros(name, weight_g)
    ai_result["source"] = "ai_estimated"
    return ai_result


async def _update_if_log(food_date: str, timestamp: datetime, db):
    """Derive IF adherence from the eating window in user_profile."""
    profile = await db.user_profile.find_one({})
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

    in_window = window_start_min <= food_time <= window_end_min

    existing = await db.if_logs.find_one({"date": food_date})
    if existing:
        # If any entry is outside window, mark non-adherent
        if not in_window:
            await db.if_logs.update_one(
                {"date": food_date}, {"$set": {"adhered": False}}
            )
    else:
        await db.if_logs.insert_one({"date": food_date, "adhered": in_window})


@router.post("/analyze")
async def analyze_food(
    photo: UploadFile = File(...),
    _: str = Depends(get_current_user),
):
    db = get_db()
    image_bytes = await photo.read()
    validate_image_upload(image_bytes, photo.filename or "", photo.content_type)

    # Upload to MinIO for storage
    filename = f"{uuid.uuid4()}.jpg"
    image_url = await minio_client.upload_image(image_bytes, minio_client.BUCKET_FOOD, filename)

    # AI food analysis
    analysis = await gemini_svc.analyze_food(image_bytes)
    items = analysis.get("items", [])
    scale_weight_g = analysis.get("scale_weight_g")

    # Bowl detection — only fetch fields needed for AI matching
    bowls_docs = await db.bowls.find(
        {}, {"_id": 1, "name": 1, "tare_weight_g": 1, "image_b64": 1}
    ).to_list(None)
    bowl_match = {}
    if bowls_docs:
        bowls_for_detection = [
            {
                "id": str(b["_id"]),
                "name": b["name"],
                "tare_weight_g": b["tare_weight_g"],
                "image_b64": b.get("image_b64", ""),
            }
            for b in bowls_docs
        ]
        if any(b["image_b64"] for b in bowls_for_detection):
            bowl_match = await gemini_svc.detect_bowl(image_bytes, bowls_for_detection)

    # Saved meal similarity check — only fetch name + item names
    saved_meals = await db.saved_meals.find(
        {}, {"_id": 1, "name": 1, "items.name": 1}
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

    # Resolve macros for each detected item so the review screen shows real values
    enriched_items = []
    for item in items:
        macros = await _resolve_macros(item["name"], item["estimated_weight_g"])
        enriched_items.append({**item, **macros})

    return {
        "items": enriched_items,
        "bowl_match": bowl_match or None,
        "scale_weight_g": scale_weight_g,
        "image_url": image_url,
        "meal_suggestion": meal_suggestion,
    }


@router.post("/logs", status_code=201)
async def create_food_log(body: FoodLogCreate, _: str = Depends(get_current_user)):
    db = get_db()
    now = datetime.now(timezone.utc)
    food_date = now.date().isoformat()

    # Resolve macros for items that don't have them
    resolved_items = []
    total_cal = total_protein = total_carbs = total_fat = 0.0

    for item in body.items:
        macros = await _resolve_macros(item.name, item.estimated_weight_g)
        resolved = item.model_dump()
        resolved.update(macros)
        resolved_items.append(resolved)
        total_cal += macros.get("calories_kcal", 0)
        total_protein += macros.get("protein_g", 0)
        total_carbs += macros.get("carbs_g", 0)
        total_fat += macros.get("fat_g", 0)

    doc = {
        "date": food_date,
        "meal_slot": body.meal_slot,
        "items": resolved_items,
        "image_url": body.image_url,
        "bowl_id": body.bowl_id,
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
        await db.food_logs.delete_many({"date": food_date, "meal_slot": MealSlot.supplement.value})

    result = await db.food_logs.insert_one(doc)

    await _update_if_log(food_date, now, db)

    doc["_id"] = str(result.inserted_id)
    return doc


@router.delete("/logs/{log_id}", status_code=204)
async def delete_food_log(log_id: str, _: str = Depends(get_current_user)):
    db = get_db()
    try:
        oid = ObjectId(log_id)
    except Exception:
        raise HTTPException(400, "Invalid log ID")
    result = await db.food_logs.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Food log not found")


@router.get("/logs")
async def get_food_logs(date: str, _: str = Depends(get_current_user)):
    """date format: YYYY-MM-DD (query param ?date=)"""
    db = get_db()
    docs = await db.food_logs.find({"date": date}).to_list(None)

    grouped: dict[str, list] = {"meal1": [], "meal2": [], "snack": [], "supplement": []}
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
async def get_daily_totals(days: int = 30, _: str = Depends(get_current_user)):
    """Returns daily aggregated calories + protein for the past N days."""
    db = get_db()
    today = date.today()
    if days > 0:
        start = (today - timedelta(days=days - 1)).isoformat()
        query: dict = {"date": {"$gte": start, "$lte": today.isoformat()}}
    else:
        query = {}

    docs = await db.food_logs.find(query).to_list(None)
    day_map: dict[str, dict] = {}
    for doc in docs:
        d = doc.get("date", "")
        if d not in day_map:
            day_map[d] = {"calories_kcal": 0.0, "protein_g": 0.0}
        t = doc.get("totals", {})
        day_map[d]["calories_kcal"] += t.get("calories_kcal", 0)
        day_map[d]["protein_g"] += t.get("protein_g", 0)

    result = sorted([
        {
            "date": d,
            "calories_kcal": round(v["calories_kcal"], 1),
            "protein_g": round(v["protein_g"], 1),
        }
        for d, v in day_map.items()
    ], key=lambda x: x["date"])
    return {"totals": result}
