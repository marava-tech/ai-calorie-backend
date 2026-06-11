"""Supplement tracker — presets + daily logs + streaks + correlation."""
import logging
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from typing import Optional

from auth import get_current_user
from database import get_db
from models.supplement import SupplementCreate, SupplementPatch, SupplementLogCreate
from services.streak_calc import consecutive_days
from utils import parse_object_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/supplements", tags=["supplements"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


# ─── Supplement presets ──────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_supplement(body: SupplementCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    doc = {
        **body.model_dump(),
        "user_id": user_id,
        "current_streak": 0,
        "best_streak": 0,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.supplements.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_supplements(
    skip: int = 0, limit: int = 50, user_id: str = Depends(get_current_user)
):
    db = get_db()
    docs = await db.supplements.find({"user_id": user_id}).skip(skip).limit(limit).to_list(None)
    return [_serialize(d) for d in docs]


@router.patch("/{supp_id}")
async def update_supplement(
    supp_id: str, body: SupplementPatch, user_id: str = Depends(get_current_user)
):
    db = get_db()
    oid = parse_object_id(supp_id, "supp_id")
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No fields provided")
    result = await db.supplements.update_one({"_id": oid, "user_id": user_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(404, "Supplement not found")
    doc = await db.supplements.find_one({"_id": oid, "user_id": user_id})
    return _serialize(doc)


@router.delete("/{supp_id}", status_code=204)
async def delete_supplement(supp_id: str, user_id: str = Depends(get_current_user)):
    db = get_db()
    oid = parse_object_id(supp_id, "supp_id")
    result = await db.supplements.delete_one({"_id": oid, "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Supplement not found")


# ─── Supplement logs ─────────────────────────────────────────────────────────

@router.post("/logs", status_code=201)
async def log_supplement(body: SupplementLogCreate, user_id: str = Depends(get_current_user)):
    db = get_db()
    supp = await db.supplements.find_one({"_id": parse_object_id(body.supplement_id, "supplement_id"), "user_id": user_id})
    if not supp:
        raise HTTPException(404, "Supplement not found")

    # Upsert: allow one log per supplement per date
    existing = await db.supplement_logs.find_one(
        {"supplement_id": body.supplement_id, "date": body.date, "user_id": user_id}
    )
    if existing:
        await db.supplement_logs.update_one(
            {"_id": existing["_id"]},
            {"$set": {"units_taken": body.units_taken, "updated_at": datetime.now(timezone.utc)}},
        )
        existing["_id"] = str(existing["_id"])
        return existing

    doc = {
        "supplement_id": body.supplement_id,
        "supplement_name": supp["name"],
        "date": body.date,
        "units_taken": body.units_taken,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.supplement_logs.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    # Update streak for this supplement
    await _update_supplement_streak(body.supplement_id, user_id, db)

    return doc


@router.get("/logs")
async def get_supplement_logs(date_str: str, user_id: str = Depends(get_current_user)):
    """Returns checklist: all supplements with taken status for the date."""
    db = get_db()
    supplements = await db.supplements.find({"user_id": user_id}).to_list(None)
    logs = await db.supplement_logs.find({"date": date_str, "user_id": user_id}).to_list(None)
    logs_by_id = {l["supplement_id"]: l for l in logs}
    taken_ids = set(logs_by_id.keys())

    today_weekday = date.fromisoformat(date_str).weekday()  # 0=Mon

    checklist = []
    for s in supplements:
        sid = str(s["_id"])
        # Weekly supplements only shown on their day_of_week
        if s.get("frequency") == "weekly":
            if s.get("day_of_week") != today_weekday:
                continue
        log = logs_by_id.get(sid)
        checklist.append({
            "supplement_id": sid,
            "id": sid,
            "name": s["name"],
            "dose_amount": s["dose_amount"],
            "dose_unit": s["dose_unit"],
            "timing": s.get("timing"),
            "taken": sid in taken_ids,
            "units_taken": log["units_taken"] if log else 0,
            "current_streak": s.get("current_streak", 0),
            "best_streak": s.get("best_streak", 0),
            "calories_per_unit": s.get("calories_per_unit", 0.0),
            "protein_per_unit": s.get("protein_per_unit", 0.0),
            "carbs_per_unit": s.get("carbs_per_unit", 0.0),
            "fat_per_unit": s.get("fat_per_unit", 0.0),
        })
    return {"date": date_str, "checklist": checklist}


async def _update_supplement_streak(supplement_id: str, user_id: str, db):
    logs = await db.supplement_logs.find(
        {"supplement_id": supplement_id, "user_id": user_id}, {"date": 1}
    ).to_list(None)
    current, best = await consecutive_days([l["date"] for l in logs])
    await db.supplements.update_one(
        {"_id": parse_object_id(supplement_id, "supplement_id"), "user_id": user_id},
        {"$set": {"current_streak": current, "best_streak": best}},
    )


# ─── Supplement-sleep correlation ────────────────────────────────────────────

@router.get("/{supp_id}/correlation")
async def supplement_correlation(
    supp_id: str,
    other: str = "sleep",
    user_id: str = Depends(get_current_user),
):
    """Compare sleep quality on supplement-taken nights vs not-taken nights."""
    db = get_db()

    supp = await db.supplements.find_one({"_id": parse_object_id(supp_id, "supp_id"), "user_id": user_id})
    if not supp:
        raise HTTPException(404, "Supplement not found")

    if other != "sleep":
        raise HTTPException(400, "Only 'sleep' correlation supported")

    supp_logs = await db.supplement_logs.find({"supplement_id": supp_id, "user_id": user_id}, {"date": 1}).to_list(None)
    supp_dates = {l["date"] for l in supp_logs}

    sleep_logs = await db.sleep_logs.find({"user_id": user_id}).to_list(None)

    QUALITY_SCORE = {"worst": 1, "bad": 2, "average": 3, "good": 4, "better": 5}

    taken_scores = []
    not_taken_scores = []
    for log in sleep_logs:
        score = QUALITY_SCORE.get(log.get("quality"), 0)
        if log["date"] in supp_dates:
            taken_scores.append(score)
        else:
            not_taken_scores.append(score)

    total = len(taken_scores) + len(not_taken_scores)
    if total < 14:
        return {
            "supplement_id": supp_id,
            "supplement_name": supp["name"],
            "status": "insufficient_data",
            "days_recorded": total,
            "required_days": 14,
        }

    avg_taken = round(sum(taken_scores) / len(taken_scores), 2) if taken_scores else 0
    avg_not_taken = round(sum(not_taken_scores) / len(not_taken_scores), 2) if not_taken_scores else 0

    return {
        "supplement_id": supp_id,
        "supplement_name": supp["name"],
        "status": "ready",
        "taken_days": len(taken_scores),
        "not_taken_days": len(not_taken_scores),
        "avg_sleep_quality_taken": avg_taken,
        "avg_sleep_quality_not_taken": avg_not_taken,
        "difference": round(avg_taken - avg_not_taken, 2),
        "insight": (
            f"{supp['name']} days: avg sleep {avg_taken}/5 vs {avg_not_taken}/5 without."
        ),
    }
