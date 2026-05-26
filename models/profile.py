from pydantic import BaseModel, Field
from typing import Optional


class NotificationPrefs(BaseModel):
    if_window: bool = True
    sleep_prompt: bool = True
    weight_reminder: bool = True
    gym_photo_nudge: bool = True
    weekly_summary: bool = True


class SleepThresholds(BaseModel):
    worst_max: float = 4.0   # < this → worst
    bad_max: float = 6.0     # < this → bad
    average_max: float = 7.0 # < this → average
    good_max: float = 8.0    # < this → good; >= this → better


class ProfileCreate(BaseModel):
    height_cm: float
    weight_kg: float
    age: int
    sex: str  # "male" | "female"
    eating_window_start: str = "13:00"  # HH:MM
    eating_window_end: str = "21:00"
    user_timezone: str = "UTC"  # IANA timezone, e.g. "Asia/Kolkata"
    notification_prefs: NotificationPrefs = Field(default_factory=NotificationPrefs)
    gym_streak_min_days_per_week: int = 5
    sleep_thresholds: SleepThresholds = Field(default_factory=SleepThresholds)
    photo_url: Optional[str] = None


class ProfilePatch(BaseModel):
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    eating_window_start: Optional[str] = None
    eating_window_end: Optional[str] = None
    user_timezone: Optional[str] = None
    notification_prefs: Optional[NotificationPrefs] = None
    fcm_token: Optional[str] = None
    gym_streak_min_days_per_week: Optional[int] = None
    sleep_thresholds: Optional[SleepThresholds] = None
    photo_url: Optional[str] = None


class TDEEResult(BaseModel):
    tdee_kcal: int
    goal_kcal: int      # TDEE + 75 (recomp)
    protein_g: int      # 2g/kg
    carbs_g: int
    fat_g: int
