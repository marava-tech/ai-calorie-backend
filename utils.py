"""Shared utility helpers."""
import logging
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def parse_object_id(value: str, label: str = "ID") -> ObjectId:
    """Parse a string into ObjectId; raises HTTP 400 on invalid format."""
    try:
        return ObjectId(value)
    except (InvalidId, Exception):
        raise HTTPException(400, f"Invalid {label}: '{value}' is not a valid ID")


def validate_image_upload(image_bytes: bytes, filename: str, content_type: str | None) -> None:
    """Raise HTTP 400 if the uploaded file exceeds size or MIME type limits."""
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Image too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)")
    mime = (content_type or "").lower()
    if mime and mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Unsupported file type '{mime}'. Use JPEG, PNG, or WebP.")
