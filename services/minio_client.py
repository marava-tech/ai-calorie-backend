"""MinIO upload via the existing minio-upload-api service."""
import os
import io
import httpx

UPLOAD_API_URL = os.environ.get("MINIO_UPLOAD_API_URL", "http://upload-api:3000")
UPLOAD_API_KEY = os.environ.get("MINIO_UPLOAD_API_KEY", "")

BUCKET = "ai-calorie-counter"

# Keep old names as aliases so call sites don't need to change
BUCKET_FOOD = BUCKET
BUCKET_GYM = BUCKET
BUCKET_BOWL = BUCKET


async def upload_image(image_bytes: bytes, bucket: str, filename: str) -> str:
    """Upload image bytes to MinIO via upload-api; returns public URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{UPLOAD_API_URL}/upload",
            headers={"x-api-key": UPLOAD_API_KEY},
            files={"file": (filename, io.BytesIO(image_bytes), "image/jpeg")},
            data={"bucket": bucket},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["url"]
