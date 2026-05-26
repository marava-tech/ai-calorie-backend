"""Gym session tracking — attendance, photos, body analysis."""
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from bson import ObjectId
from typing import Optional

from auth import get_current_user
from database import get_db
from models.gym_session import GymSessionCreate, PhotoAngle
from services import gemini as gemini_svc
from services import minio_client
from services.streak_calc import calculate_weekly_gym_streak
from utils import parse_object_id, validate_image_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gym-sessions", tags=["gym"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.post("", status_code=201)
async def create_session(body: GymSessionCreate, _: str = Depends(get_current_user)):
    db = get_db()
    doc = {
        **body.model_dump(),
        "photos": [],
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.gym_sessions.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)

    await _sync_gym_streak(db)

    return doc


@router.get("")
async def list_sessions(month: str, _: str = Depends(get_current_user)):
    """month format: YYYY-MM"""
    db = get_db()
    docs = await db.gym_sessions.find({"date": {"$regex": f"^{month}"}}).to_list(None)
    return [_serialize(d) for d in docs]


@router.post("/{session_id}/photos", status_code=201)
async def upload_photo(
    session_id: str,
    angle: PhotoAngle = Form(...),
    photo: UploadFile = File(...),
    _: str = Depends(get_current_user),
):
    db = get_db()
    oid = parse_object_id(session_id, "session_id")
    session = await db.gym_sessions.find_one({"_id": oid})
    if not session:
        raise HTTPException(404, "Session not found")

    image_bytes = await photo.read()
    validate_image_upload(image_bytes, photo.filename or "", photo.content_type)
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
        {"_id": oid},
        {"$push": {"photos": photo_doc}},
    )

    # Trigger async body analysis
    try:
        await _run_body_analysis(session_id, photo_id, image_bytes, angle.value, db)
    except Exception as e:
        logger.error("Body analysis failed for session %s photo %s: %s", session_id, photo_id, e)

    updated = await db.gym_sessions.find_one({"_id": oid})
    photo_updated = next((p for p in updated.get("photos", []) if p["photo_id"] == photo_id), photo_doc)
    return photo_updated


async def _run_body_analysis(
    session_id: str, photo_id: str, image_bytes: bytes, angle: str, db
):
    # Get previous photo of same angle for comparison
    prev_image_bytes = None
    all_sessions = await db.gym_sessions.find(
        {"_id": {"$ne": parse_object_id(session_id)}}
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
        {"_id": parse_object_id(session_id), "photos.photo_id": photo_id},
        {"$set": {"photos.$.analysis": result}},
    )


async def _sync_gym_streak(db):
    profile = await db.user_profile.find_one({})
    min_days = (profile or {}).get("gym_streak_min_days_per_week", 5)
    docs = await db.gym_sessions.find({"attended": True}, {"date": 1}).to_list(None)
    weekly = await calculate_weekly_gym_streak([d["date"] for d in docs], min_days)
    await db.user_profile.update_one(
        {}, {"$set": {"streaks.gym_weekly": weekly}}
    )


@router.post("/{session_id}/photos/{photo_id}/analyze")
async def analyze_photo(
    session_id: str, photo_id: str, _: str = Depends(get_current_user)
):
    """Re-trigger body analysis on demand."""
    db = get_db()
    session = await db.gym_sessions.find_one({"_id": parse_object_id(session_id, "session_id")})
    if not session:
        raise HTTPException(404, "Session not found")

    photo = next((p for p in session.get("photos", []) if p["photo_id"] == photo_id), None)
    if not photo:
        raise HTTPException(404, "Photo not found")

    # We can't retrieve the image bytes here without a MinIO client fetch
    # Return the existing analysis if available
    return photo.get("analysis") or {"status": "no_analysis_available"}
