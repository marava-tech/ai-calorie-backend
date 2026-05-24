from pydantic import BaseModel, Field
from typing import Optional


class NotificationPrefs(BaseModel):
    if_window: bool = True
    sleep_prompt: bool = True
    weight_reminder: bool = True
    gym_photo_nudge: bool = True
    weekly_summary: bool = True


class ProfileCreate(BaseModel):
    height_cm: float
    weight_kg: float
    age: int
    sex: str  # "male" | "female"
    eating_window_start: str = "13:00"  # HH:MM
    eating_window_end: str = "21:00"
    user_timezone: str = "UTC"  # IANA timezone, e.g. "Asia/Kolkata"
    notification_prefs: NotificationPrefs = Field(default_factory=NotificationPrefs)


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


class TDEEResult(BaseModel):
    tdee_kcal: int
    goal_kcal: int      # TDEE + 75 (recomp)
    protein_g: int      # 2g/kg
    carbs_g: int
    fat_g: int
