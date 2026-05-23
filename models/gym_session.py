from pydantic import BaseModel
from typing import Optional
from enum import Enum


class WorkoutType(str, Enum):
    push = "push"
    pull = "pull"
    legs = "legs"
    full_body = "full_body"
    cardio = "cardio"
    other = "other"


class GymSessionCreate(BaseModel):
    date: str          # YYYY-MM-DD
    workout_type: WorkoutType = WorkoutType.other
    attended: bool = True
    notes: Optional[str] = None


class PhotoAngle(str, Enum):
    front = "front"
    back = "back"
    side = "side"
