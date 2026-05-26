from typing import Optional
from pydantic import BaseModel


class WeightPhotoCreate(BaseModel):
    weight_kg: Optional[float] = None
    photo_date: str  # YYYY-MM-DD
