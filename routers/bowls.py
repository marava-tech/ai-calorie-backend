"""Bowl preset management — CRUD + AI description generation."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from bson import ObjectId

from auth import verify_api_key
from database import get_db
from models.bowl import BowlPatch
from services import gemini as gemini_svc
from services import minio_client

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
    _: str = Depends(verify_api_key),
):
    db = get_db()
    image_bytes = await photo.read()

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
async def list_bowls(_: str = Depends(verify_api_key)):
    db = get_db()
    docs = await db.bowls.find({}).to_list(None)
    return [_serialize(d) for d in docs]


@router.patch("/{bowl_id}")
async def update_bowl(bowl_id: str, body: BowlPatch, _: str = Depends(verify_api_key)):
    db = get_db()
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No fields provided")
    result = await db.bowls.update_one({"_id": ObjectId(bowl_id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(404, "Bowl not found")
    doc = await db.bowls.find_one({"_id": ObjectId(bowl_id)})
    return _serialize(doc)


@router.delete("/{bowl_id}", status_code=204)
async def delete_bowl(bowl_id: str, _: str = Depends(verify_api_key)):
    db = get_db()
    result = await db.bowls.delete_one({"_id": ObjectId(bowl_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Bowl not found")
