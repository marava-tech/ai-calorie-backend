from pydantic import BaseModel
from typing import Optional


class BowlCreate(BaseModel):
    name: str
    tare_weight_g: float = 0
    ai_description: Optional[str] = None


class BowlPatch(BaseModel):
    name: Optional[str] = None
    tare_weight_g: Optional[float] = None
    ai_description: Optional[str] = None
