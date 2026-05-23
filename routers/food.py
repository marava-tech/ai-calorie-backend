"""Food logging — AI analysis pipeline + CRUD for logs."""
import uuid
import base64
from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from bson import ObjectId
from typing import Optional

from auth import verify_api_key
from database import get_db
from models.food_log import FoodLogCreate, FoodItem, MacroSource, MealSlot
from services import gemini as gemini_svc
from services import minio_client
from services.openfoodfacts import lookup_macros

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

    start_h, start_m = map(int, window_start.split(":"))
    end_h, end_m = map(int, window_end.split(":"))

    # Convert UTC timestamp to local naive time for comparison
    t = timestamp.replace(tzinfo=None)
    food_time = t.hour * 60 + t.minute
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
    _: str = Depends(verify_api_key),
):
    db = get_db()
    image_bytes = await photo.read()

    # Upload to MinIO for storage
    filename = f"{uuid.uuid4()}.jpg"
    image_url = await minio_client.upload_image(image_bytes, minio_client.BUCKET_FOOD, filename)

    # AI food analysis
    analysis = await gemini_svc.analyze_food(image_bytes)
    items = analysis.get("items", [])
    scale_weight_g = analysis.get("scale_weight_g")

    # Bowl detection
    bowls_docs = await db.bowls.find({}).to_list(None)
    bowl_match = {}
    if bowls_docs:
        bowls_for_detection = []
        for b in bowls_docs:
            # Fetch bowl image for comparison
            bowls_for_detection.append({
                "id": str(b["_id"]),
                "name": b["name"],
                "tare_weight_g": b["tare_weight_g"],
                "image_b64": b.get("image_b64", ""),
            })
        if any(b["image_b64"] for b in bowls_for_detection):
            bowl_match = await gemini_svc.detect_bowl(image_bytes, bowls_for_detection)

    # Saved meal similarity check
    saved_meals = await db.saved_meals.find({}).to_list(None)
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

    return {
        "items": items,
        "bowl_match": bowl_match or None,
        "scale_weight_g": scale_weight_g,
        "image_url": image_url,
        "meal_suggestion": meal_suggestion,
    }


@router.post("/logs", status_code=201)
async def create_food_log(body: FoodLogCreate, _: str = Depends(verify_api_key)):
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
    result = await db.food_logs.insert_one(doc)

    await _update_if_log(food_date, now, db)

    doc["_id"] = str(result.inserted_id)
    return doc


@router.get("/logs")
async def get_food_logs(date_str: str, _: str = Depends(verify_api_key)):
    """date_str format: YYYY-MM-DD (query param ?date=)"""
    db = get_db()
    docs = await db.food_logs.find({"date": date_str}).to_list(None)

    grouped: dict[str, list] = {"meal1": [], "meal2": [], "snack": []}
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
        "date": date_str,
        "entries": grouped,
        "slot_totals": slot_totals,
        "day_total": {k: round(v, 1) for k, v in day_total.items()},
    }
