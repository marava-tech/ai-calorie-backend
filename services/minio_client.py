"""MinIO upload via the existing minio-upload-api service."""
import os
import io
import httpx

UPLOAD_API_URL = os.environ.get("MINIO_UPLOAD_API_URL", "http://minio-upload-api:3000")

BUCKET_FOOD = "fitness-food-photos"
BUCKET_GYM = "fitness-gym-photos"
BUCKET_BOWL = "fitness-bowl-photos"


async def upload_image(image_bytes: bytes, bucket: str, filename: str) -> str:
    """Upload image bytes to MinIO via upload-api; returns public URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{UPLOAD_API_URL}/upload",
            files={"file": (filename, io.BytesIO(image_bytes), "image/jpeg")},
            data={"bucket": bucket},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["url"]
