from pydantic import BaseModel
from typing import Optional


class BowlCreate(BaseModel):
    name: str
    tare_weight_g: float
    ai_description: Optional[str] = None  # editable after AI generation


class BowlPatch(BaseModel):
    name: Optional[str] = None
    tare_weight_g: Optional[float] = None
    ai_description: Optional[str] = None
