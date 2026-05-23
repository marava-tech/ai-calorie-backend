from pydantic import BaseModel
from typing import Optional
from enum import Enum


class Frequency(str, Enum):
    daily = "daily"
    weekly = "weekly"


class SupplementCreate(BaseModel):
    name: str
    dose_amount: float
    dose_unit: str = "g"
    frequency: Frequency = Frequency.daily
    day_of_week: Optional[int] = None  # 0=Mon..6=Sun, used when weekly
    timing: Optional[str] = None       # "morning", "post-workout", etc.
    calories_per_unit: float = 0.0
    protein_per_unit: float = 0.0
    carbs_per_unit: float = 0.0
    fat_per_unit: float = 0.0


class SupplementPatch(BaseModel):
    name: Optional[str] = None
    dose_amount: Optional[float] = None
    dose_unit: Optional[str] = None
    frequency: Optional[Frequency] = None
    day_of_week: Optional[int] = None
    timing: Optional[str] = None
    calories_per_unit: Optional[float] = None
    protein_per_unit: Optional[float] = None
    carbs_per_unit: Optional[float] = None
    fat_per_unit: Optional[float] = None


class SupplementLogCreate(BaseModel):
    supplement_id: str
    date: str   # YYYY-MM-DD
    units_taken: float = 1.0
