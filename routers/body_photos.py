"""Standalone body photo uploads — decoupled from gym sessions."""
import logging
import uuid
from datetime import datetime, timezone, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from enum import Enum

from auth import get_current_user
from database import get_db
from services import gemini as gemini_svc
from services import minio_client
from utils import validate_image_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/body-photos", tags=["body-photos"])


class BodyPhotoAngle(str, Enum):
    front = "front"
    back = "back"
    side = "side"


@router.post("", status_code=201)
async def upload_body_photo(
    angle: BodyPhotoAngle = Form(...),
    photo_date: str = Form(...),  # YYYY-MM-DD
    photo: UploadFile = File(...),
    _: str = Depends(get_current_user),
):
    db = get_db()

    image_bytes = await photo.read()
    validate_image_upload(image_bytes, photo.filename or "", photo.content_type)

    filename = f"{uuid.uuid4()}.jpg"
    image_url = await minio_client.upload_image(image_bytes, minio_client.BUCKET_GYM, filename)

    photo_id = str(uuid.uuid4())
    doc = {
        "photo_id": photo_id,
        "date": photo_date,
        "angle": angle.value,
        "image_url": image_url,
        "analysis": None,
        "created_at": datetime.now(timezone.utc),
    }
    await db.body_photos.insert_one(doc)
    doc["_id"] = str(doc.pop("_id", photo_id))

    # Run Gemini body analysis async — non-blocking
    try:
        await _run_analysis(photo_id, image_bytes, angle.value, db)
    except Exception as e:
        logger.error("Body analysis failed for body_photo %s: %s", photo_id, e)

    # Return updated doc with analysis if it completed
    updated = await db.body_photos.find_one({"photo_id": photo_id})
    if updated:
        updated["_id"] = str(updated["_id"])
        return updated
    return doc


async def _run_analysis(photo_id: str, image_bytes: bytes, angle: str, db):
    result = await gemini_svc.analyze_body_photo(image_bytes, None, angle)
    await db.body_photos.update_one(
        {"photo_id": photo_id},
        {"$set": {"analysis": result}},
    )


class CompareRequest(BaseModel):
    photo_ids: list[str]


@router.post("/compare")
async def compare_body_photos(req: CompareRequest, _: str = Depends(get_current_user)):
    """Compare 2–3 body photos using AI visual progression analysis."""
    if len(req.photo_ids) < 2 or len(req.photo_ids) > 3:
        raise HTTPException(status_code=400, detail="Select 2 or 3 photos to compare")

    db = get_db()
    docs = []
    for pid in req.photo_ids:
        doc = await db.body_photos.find_one({"photo_id": pid})
        if not doc:
            raise HTTPException(status_code=404, detail=f"Photo {pid} not found")
        docs.append(doc)

    angles = {d["angle"] for d in docs}
    if len(angles) > 1:
        raise HTTPException(status_code=400, detail="All selected photos must be the same angle")

    photos_payload = []
    for doc in docs:
        image_bytes = await minio_client.download_image(doc["image_url"])
        photos_payload.append({
            "image_bytes": image_bytes,
            "date": doc["date"],
            "angle": doc["angle"],
            "photo_id": doc["photo_id"],
            "image_url": doc["image_url"],
        })

    comparison = await gemini_svc.compare_body_photos(photos_payload)

    return {
        "photos": [
            {"photo_id": d["photo_id"], "date": d["date"], "angle": d["angle"], "image_url": d["image_url"]}
            for d in sorted(docs, key=lambda x: x["date"])
        ],
        "comparison": comparison,
    }


@router.get("")
async def list_body_photos(days: int = 90, _: str = Depends(get_current_user)):
    db = get_db()
    query: dict = {}
    if days > 0:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        query["date"] = {"$gte": cutoff}
    docs = await db.body_photos.find(query).sort("date", -1).to_list(None)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"photos": docs}
