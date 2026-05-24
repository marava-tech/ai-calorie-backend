"""Bowl preset management — CRUD + AI description generation."""
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from auth import get_current_user
from database import get_db
from models.bowl import BowlPatch
from services import gemini as gemini_svc
from services import minio_client
from utils import parse_object_id, validate_image_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bowls", tags=["bowls"])


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.post("", status_code=201)
async def create_bowl(
    name: str = Form(...),
    tare_weight_g: float = Form(...),
    ai_description: str = Form(""),
    photo: UploadFile = File(...),
    _: str = Depends(get_current_user),
):
    db = get_db()
    image_bytes = await photo.read()
    validate_image_upload(image_bytes, photo.filename or "", photo.content_type)

    # Upload to MinIO
    filename = f"{uuid.uuid4()}.jpg"
    image_url = await minio_client.upload_image(image_bytes, minio_client.BUCKET_BOWL, filename)

    # Generate AI description if not supplied
    if not ai_description:
        ai_description = await gemini_svc.describe_bowl(image_bytes)

    doc = {
        "name": name,
        "tare_weight_g": tare_weight_g,
        "ai_description": ai_description,
        "image_url": image_url,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.bowls.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_bowls(
    skip: int = 0, limit: int = 50, _: str = Depends(get_current_user)
):
    db = get_db()
    docs = await db.bowls.find({}).skip(skip).limit(limit).to_list(None)
    return [_serialize(d) for d in docs]


@router.patch("/{bowl_id}")
async def update_bowl(bowl_id: str, body: BowlPatch, _: str = Depends(get_current_user)):
    db = get_db()
    oid = parse_object_id(bowl_id, "bowl_id")
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No fields provided")
    result = await db.bowls.update_one({"_id": oid}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(404, "Bowl not found")
    doc = await db.bowls.find_one({"_id": oid})
    return _serialize(doc)


@router.delete("/{bowl_id}", status_code=204)
async def delete_bowl(bowl_id: str, _: str = Depends(get_current_user)):
    db = get_db()
    oid = parse_object_id(bowl_id, "bowl_id")
    result = await db.bowls.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Bowl not found")
