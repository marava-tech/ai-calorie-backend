"""Saved meal library — CRUD."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId

from auth import get_current_user
from database import get_db
from models.saved_meal import SavedMealCreate, SavedMealPatch

router = APIRouter(prefix="/api/saved-meals", tags=["saved-meals"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.post("", status_code=201)
async def create_saved_meal(body: SavedMealCreate, _: str = Depends(get_current_user)):
    db = get_db()
    totals = {"calories_kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for item in body.items:
        totals["calories_kcal"] += item.calories_kcal
        totals["protein_g"] += item.protein_g
        totals["carbs_g"] += item.carbs_g
        totals["fat_g"] += item.fat_g

    doc = {
        **body.model_dump(),
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "use_count": 0,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.saved_meals.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_saved_meals(_: str = Depends(get_current_user)):
    db = get_db()
    docs = await db.saved_meals.find({}).sort("use_count", -1).to_list(None)
    return [_serialize(d) for d in docs]


@router.patch("/{meal_id}")
async def update_saved_meal(
    meal_id: str, body: SavedMealPatch, _: str = Depends(get_current_user)
):
    db = get_db()
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No fields provided")
    result = await db.saved_meals.update_one(
        {"_id": ObjectId(meal_id)}, {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Saved meal not found")
    doc = await db.saved_meals.find_one({"_id": ObjectId(meal_id)})
    return _serialize(doc)


@router.delete("/{meal_id}", status_code=204)
async def delete_saved_meal(meal_id: str, _: str = Depends(get_current_user)):
    db = get_db()
    result = await db.saved_meals.delete_one({"_id": ObjectId(meal_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Saved meal not found")


@router.post("/{meal_id}/use", status_code=201)
async def use_saved_meal(meal_id: str, meal_slot: str, _: str = Depends(get_current_user)):
    """Log a saved meal directly to food_logs and increment use_count."""
    db = get_db()
    meal = await db.saved_meals.find_one({"_id": ObjectId(meal_id)})
    if not meal:
        raise HTTPException(404, "Saved meal not found")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    doc = {
        "date": now.date().isoformat(),
        "meal_slot": meal_slot,
        "items": meal["items"],
        "image_url": meal.get("image_url"),
        "bowl_id": None,
        "note": f"Saved meal: {meal['name']}",
        "totals": meal["totals"],
        "created_at": now,
    }
    result = await db.food_logs.insert_one(doc)
    await db.saved_meals.update_one({"_id": ObjectId(meal_id)}, {"$inc": {"use_count": 1}})
    doc["_id"] = str(result.inserted_id)
    return doc
