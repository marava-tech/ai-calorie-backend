"""Supplement tracker — presets + daily logs + streaks + correlation."""
from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from typing import Optional

from auth import verify_api_key
from database import get_db
from models.supplement import SupplementCreate, SupplementPatch, SupplementLogCreate

router = APIRouter(prefix="/api/supplements", tags=["supplements"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


# ─── Supplement presets ──────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_supplement(body: SupplementCreate, _: str = Depends(verify_api_key)):
    db = get_db()
    doc = {
        **body.model_dump(),
        "current_streak": 0,
        "best_streak": 0,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.supplements.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_supplements(_: str = Depends(verify_api_key)):
    db = get_db()
    docs = await db.supplements.find({}).to_list(None)
    return [_serialize(d) for d in docs]


@router.patch("/{supp_id}")
async def update_supplement(
    supp_id: str, body: SupplementPatch, _: str = Depends(verify_api_key)
):
    db = get_db()
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No fields provided")
    result = await db.supplements.update_one(
        {"_id": ObjectId(supp_id)}, {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Supplement not found")
    doc = await db.supplements.find_one({"_id": ObjectId(supp_id)})
    return _serialize(doc)


@router.delete("/{supp_id}", status_code=204)
async def delete_supplement(supp_id: str, _: str = Depends(verify_api_key)):
    db = get_db()
    result = await db.supplements.delete_one({"_id": ObjectId(supp_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Supplement not found")


# ─── Supplement logs ─────────────────────────────────────────────────────────

@router.post("/logs", status_code=201)
async def log_supplement(body: SupplementLogCreate, _: str = Depends(verify_api_key)):
    db = get_db()
    supp = await db.supplements.find_one({"_id": ObjectId(body.supplement_id)})
    if not supp:
        raise HTTPException(404, "Supplement not found")

    # Upsert: allow one log per supplement per date
    existing = await db.supplement_logs.find_one(
        {"supplement_id": body.supplement_id, "date": body.date}
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
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.supplement_logs.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    # Update streak for this supplement
    await _update_supplement_streak(body.supplement_id, db)

    return doc


@router.get("/logs")
async def get_supplement_logs(date_str: str, _: str = Depends(verify_api_key)):
    """Returns checklist: all supplements with taken status for the date."""
    db = get_db()
    supplements = await db.supplements.find({}).to_list(None)
    logs = await db.supplement_logs.find({"date": date_str}).to_list(None)
    taken_ids = {l["supplement_id"] for l in logs}

    today_weekday = date.fromisoformat(date_str).weekday()  # 0=Mon

    checklist = []
    for s in supplements:
        sid = str(s["_id"])
        # Weekly supplements only shown on their day_of_week
        if s.get("frequency") == "weekly":
            if s.get("day_of_week") != today_weekday:
                continue
        log = next((l for l in logs if l["supplement_id"] == sid), None)
        checklist.append({
            "supplement_id": sid,
            "name": s["name"],
            "dose_amount": s["dose_amount"],
            "dose_unit": s["dose_unit"],
            "timing": s.get("timing"),
            "taken": sid in taken_ids,
            "units_taken": log["units_taken"] if log else 0,
            "current_streak": s.get("current_streak", 0),
            "best_streak": s.get("best_streak", 0),
        })
    return {"date": date_str, "checklist": checklist}


async def _update_supplement_streak(supplement_id: str, db):
    logs = await db.supplement_logs.find(
        {"supplement_id": supplement_id}, {"date": 1}
    ).sort("date", 1).to_list(None)

    dates = sorted({l["date"] for l in logs})
    if not dates:
        return

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    current = 1
    best = 1
    for i in range(1, len(dates)):
        prev = date.fromisoformat(dates[i - 1])
        curr = date.fromisoformat(dates[i])
        if (curr - prev).days == 1:
            current += 1
            best = max(best, current)
        else:
            current = 1

    if dates[-1] not in (today, yesterday):
        current = 0

    await db.supplements.update_one(
        {"_id": ObjectId(supplement_id)},
        {"$set": {"current_streak": current, "best_streak": best}},
    )


# ─── Supplement-sleep correlation ────────────────────────────────────────────

@router.get("/{supp_id}/correlation")
async def supplement_correlation(
    supp_id: str,
    other: str = "sleep",
    _: str = Depends(verify_api_key),
):
    """Compare sleep quality on supplement-taken nights vs not-taken nights."""
    db = get_db()

    supp = await db.supplements.find_one({"_id": ObjectId(supp_id)})
    if not supp:
        raise HTTPException(404, "Supplement not found")

    if other != "sleep":
        raise HTTPException(400, "Only 'sleep' correlation supported")

    supp_logs = await db.supplement_logs.find({"supplement_id": supp_id}, {"date": 1}).to_list(None)
    supp_dates = {l["date"] for l in supp_logs}

    sleep_logs = await db.sleep_logs.find({}).to_list(None)

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
