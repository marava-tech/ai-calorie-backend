"""Image upload via s3.marava.tech."""
import io
import httpx

UPLOAD_URL = "https://s3.marava.tech/upload"
UPLOAD_API_KEY = "REDACTED_UPLOAD_API_KEY"
BUCKET = "ai-calorie-counter"

BUCKET_FOOD = BUCKET
BUCKET_GYM = BUCKET
BUCKET_BOWL = BUCKET
BUCKET_PROFILE = BUCKET


async def upload_image(image_bytes: bytes, bucket: str, filename: str) -> str:
    """Upload image bytes to s3.marava.tech; returns public URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            UPLOAD_URL,
            headers={"x-api-key": UPLOAD_API_KEY},
            files={"file": (filename, io.BytesIO(image_bytes), "image/jpeg")},
            data={"bucket": bucket},
        )
        resp.raise_for_status()
        return resp.json()["url"]
