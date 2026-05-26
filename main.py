"""Fitness OS — FastAPI backend (port 8850)."""
import os
import logging
import logging.config
from contextlib import asynccontextmanager
from datetime import datetime, timezone, date, timedelta

from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import get_db, ensure_indexes
from services import fcm as fcm_svc

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("fitness_os")

# ─── Required environment variable check ─────────────────────────────────────
_REQUIRED_ENV = ["MONGODB_URI", "JWT_SECRET", "GEMINI_API_KEY", "FIREBASE_PROJECT_ID"]

def _check_env():
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

from routers import (
    auth_router,
    profile,
    bowls,
    food,
    saved_meals,
    supplements,
    gym,
    body_analysis,
    body_photos,
    sleep,
    weight,
    streaks,
    summary,
    notifications,
    daily_checkin,
)

scheduler = AsyncIOScheduler()


async def _send_weekly_summary():
    """Send FCM notification for weekly summary every Sunday 8pm."""
    db = get_db()
    profile_doc = await db.user_profile.find_one({})
    if profile_doc and profile_doc.get("fcm_token"):
        prefs = profile_doc.get("notification_prefs", {})
        if prefs.get("weekly_summary", True):
            week = date.today().strftime("%Y-W%W")
            try:
                await fcm_svc.send_notification(
                    profile_doc["fcm_token"],
                    "Weekly Summary Ready",
                    "Your fitness week is complete — tap to see your summary.",
                    {"week": week},
                )
            except Exception as e:
                logger.error("Failed to send weekly summary FCM: %s", e)


async def _check_gym_photo_nudge():
    """Send FCM if no gym photo uploaded in last 7 days."""
    db = get_db()
    profile_doc = await db.user_profile.find_one({})
    if not profile_doc or not profile_doc.get("fcm_token"):
        return
    prefs = profile_doc.get("notification_prefs", {})
    if not prefs.get("gym_photo_nudge", True):
        return

    cutoff = (date.today() - timedelta(days=7)).isoformat()
    recent = await db.gym_sessions.find_one(
        {"date": {"$gte": cutoff}, "photos": {"$ne": []}}
    )
    if not recent:
        try:
            await fcm_svc.send_notification(
                profile_doc["fcm_token"],
                "Progress Photo Reminder",
                "No gym photos in 7 days — capture your progress!",
            )
        except Exception as e:
            logger.error("Failed to send gym photo nudge FCM: %s", e)


async def _send_daily_quiz_reminder():
    """Send daily 10pm IST check-in reminder (runs at 16:30 UTC)."""
    db = get_db()
    profile_doc = await db.user_profile.find_one({})
    if not profile_doc or not profile_doc.get("fcm_token"):
        return
    prefs = profile_doc.get("notification_prefs", {})
    if not prefs.get("daily_checkin_reminder", True):
        return
    try:
        await fcm_svc.send_notification(
            profile_doc["fcm_token"],
            "Time for your daily check-in! 📋",
            "Log your supplements, gym, and sleep for today.",
        )
    except Exception as e:
        logger.error("Failed to send daily quiz reminder FCM: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_env()
    await ensure_indexes()
    # Sunday at 20:00 UTC — weekly summary FCM
    scheduler.add_job(_send_weekly_summary, "cron", day_of_week="sun", hour=20, minute=0)
    # Daily at 09:00 UTC — gym photo nudge check
    scheduler.add_job(_check_gym_photo_nudge, "cron", hour=9, minute=0)
    # Daily at 16:30 UTC (22:00 IST) — daily check-in reminder
    scheduler.add_job(_send_daily_quiz_reminder, "cron", hour=16, minute=30)
    scheduler.start()
    logger.info("Fitness OS backend started")
    yield
    scheduler.shutdown()
    logger.info("Fitness OS backend stopped")


app = FastAPI(
    title="Fitness OS API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(auth_router.router)
app.include_router(profile.router)
app.include_router(bowls.router)
app.include_router(food.router)
app.include_router(saved_meals.router)
app.include_router(supplements.router)
app.include_router(gym.router)
app.include_router(body_analysis.router)
app.include_router(body_photos.router)
app.include_router(sleep.router)
app.include_router(weight.router)
app.include_router(streaks.router)
app.include_router(summary.router)
app.include_router(notifications.router)
app.include_router(daily_checkin.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "fitness-os",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
