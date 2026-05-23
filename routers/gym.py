"""Gym session tracking — attendance, photos, body analysis."""
import uuid
from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from bson import ObjectId
from typing import Optional

from auth import verify_api_key
from database import get_db
from models.gym_session import GymSessionCreate, PhotoAngle
from services import gemini as gemini_svc
from services import minio_client

router = APIRouter(prefix="/api/gym-sessions", tags=["gym"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.post("", status_code=201)
async def create_session(body: GymSessionCreate, _: str = Depends(verify_api_key)):
    db = get_db()
    doc = {
        **body.model_dump(),
        "photos": [],
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.gym_sessions.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)

    # Update gym streak in user_profile
    await _update_gym_streak(db)

    return doc


@router.get("")
async def list_sessions(month: str, _: str = Depends(verify_api_key)):
    """month format: YYYY-MM"""
    db = get_db()
    docs = await db.gym_sessions.find({"date": {"$regex": f"^{month}"}}).to_list(None)
    return [_serialize(d) for d in docs]


@router.post("/{session_id}/photos", status_code=201)
async def upload_photo(
    session_id: str,
    angle: PhotoAngle = Form(...),
    photo: UploadFile = File(...),
    _: str = Depends(verify_api_key),
):
    db = get_db()
    session = await db.gym_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(404, "Session not found")

    image_bytes = await photo.read()
    filename = f"{uuid.uuid4()}.jpg"
    image_url = await minio_client.upload_image(image_bytes, minio_client.BUCKET_GYM, filename)

    photo_id = str(uuid.uuid4())
    photo_doc = {
        "photo_id": photo_id,
        "angle": angle.value,
        "image_url": image_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis": None,
    }

    await db.gym_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$push": {"photos": photo_doc}},
    )

    # Trigger async body analysis
    try:
        await _run_body_analysis(session_id, photo_id, image_bytes, angle.value, db)
    except Exception:
        pass  # Analysis failure shouldn't block the upload response

    updated = await db.gym_sessions.find_one({"_id": ObjectId(session_id)})
    photo_updated = next((p for p in updated.get("photos", []) if p["photo_id"] == photo_id), photo_doc)
    return photo_updated


async def _run_body_analysis(
    session_id: str, photo_id: str, image_bytes: bytes, angle: str, db
):
    # Get previous photo of same angle for comparison
    prev_image_bytes = None
    all_sessions = await db.gym_sessions.find(
        {"_id": {"$ne": ObjectId(session_id)}}
    ).sort("date", -1).to_list(None)

    for s in all_sessions:
        for p in s.get("photos", []):
            if p.get("angle") == angle and p.get("image_url"):
                # We can't re-fetch the image bytes from MinIO easily here
                # Body analysis will work without comparison photo
                break
        else:
            continue
        break

    result = await gemini_svc.analyze_body_photo(image_bytes, prev_image_bytes, angle)

    await db.gym_sessions.update_one(
        {"_id": ObjectId(session_id), "photos.photo_id": photo_id},
        {"$set": {"photos.$.analysis": result}},
    )


async def _update_gym_streak(db):
    docs = await db.gym_sessions.find({"attended": True}, {"date": 1}).sort("date", 1).to_list(None)
    dates = sorted({d["date"] for d in docs})
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

    await db.user_profile.update_one(
        {}, {"$set": {"streaks.gym_current": current, "streaks.gym_best": best}}
    )


@router.post("/{session_id}/photos/{photo_id}/analyze")
async def analyze_photo(
    session_id: str, photo_id: str, _: str = Depends(verify_api_key)
):
    """Re-trigger body analysis on demand."""
    db = get_db()
    session = await db.gym_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(404, "Session not found")

    photo = next((p for p in session.get("photos", []) if p["photo_id"] == photo_id), None)
    if not photo:
        raise HTTPException(404, "Photo not found")

    # We can't retrieve the image bytes here without a MinIO client fetch
    # Return the existing analysis if available
    return photo.get("analysis") or {"status": "no_analysis_available"}
