import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(os.environ["MONGODB_URI"])
    return _client


def get_db():
    return get_client()["fitness_os"]


async def ensure_indexes():
    db = get_db()
    # date indexes — used in almost every range query
    for collection in [
        "food_logs", "weight_photos", "sleep_logs",
        "gym_sessions", "daily_checkins", "if_logs", "supplement_logs",
    ]:
        await db[collection].create_index([("date", 1)], background=True)
    # supplement lookup by ID
    await db.supplement_logs.create_index([("supplement_id", 1)], background=True)
    logger.info("MongoDB indexes ensured")
