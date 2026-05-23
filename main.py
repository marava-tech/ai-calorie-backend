"""Fitness OS — FastAPI backend (port 8850)."""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, date, timedelta

from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import get_db
from services import fcm as fcm_svc

from routers import (
    profile,
    bowls,
    food,
    saved_meals,
    supplements,
    gym,
    body_analysis,
    sleep,
    weight,
    streaks,
    summary,
    notifications,
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
            except Exception:
                pass


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
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sunday at 20:00 — weekly summary FCM
    scheduler.add_job(_send_weekly_summary, "cron", day_of_week="sun", hour=20, minute=0)
    # Daily at 09:00 — gym photo nudge check
    scheduler.add_job(_check_gym_photo_nudge, "cron", hour=9, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Fitness OS API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(profile.router)
app.include_router(bowls.router)
app.include_router(food.router)
app.include_router(saved_meals.router)
app.include_router(supplements.router)
app.include_router(gym.router)
app.include_router(body_analysis.router)
app.include_router(sleep.router)
app.include_router(weight.router)
app.include_router(streaks.router)
app.include_router(summary.router)
app.include_router(notifications.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "fitness-os"}
