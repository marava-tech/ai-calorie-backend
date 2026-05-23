from pydantic import BaseModel
from typing import Optional, List
from .food_log import FoodItem


class SavedMealCreate(BaseModel):
    name: str
    items: List[FoodItem]
    image_url: Optional[str] = None


class SavedMealPatch(BaseModel):
    name: Optional[str] = None
    items: Optional[List[FoodItem]] = None
    image_url: Optional[str] = None
