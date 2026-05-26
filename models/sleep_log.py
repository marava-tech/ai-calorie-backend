from pydantic import BaseModel
from enum import Enum


class SleepQuality(str, Enum):
    worst = "worst"
    bad = "bad"
    average = "average"
    good = "good"
    better = "better"


class SleepLogCreate(BaseModel):
    date: str           # YYYY-MM-DD (night of sleep)
    hours_slept: float  # quality is auto-derived from this
