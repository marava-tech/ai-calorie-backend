from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class MealSlot(str, Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    extras = "extras"
    supplement = "supplement"
    # Legacy values — kept for backward compatibility
    meal1 = "meal1"
    meal2 = "meal2"
    snack = "snack"


class MacroSource(str, Enum):
    database = "database"
    ai_estimated = "ai_estimated"


class FoodItem(BaseModel):
    name: str
    estimated_weight_g: float
    calories_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    macro_source: MacroSource = MacroSource.ai_estimated


class FoodLogCreate(BaseModel):
    meal_slot: MealSlot
    items: List[FoodItem]
    image_url: Optional[str] = None
    note: Optional[str] = None


class AnalyzeRequest(BaseModel):
    # For when analysis result comes back and needs macro lookup
    pass


class AnalyzedItem(BaseModel):
    name: str
    estimated_weight_g: float
    source: str = "ai"


class FoodAnalysisResponse(BaseModel):
    items: List[AnalyzedItem]
    scale_weight_g: Optional[float] = None
    image_url: str
