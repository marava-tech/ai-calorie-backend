from pydantic import BaseModel
from typing import Optional


class SavedFoodCreate(BaseModel):
    name: str
    estimated_weight_g: float
    calories_kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    macro_source: str = "ai_estimated"
    image_url: Optional[str] = None
