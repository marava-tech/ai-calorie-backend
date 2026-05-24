from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class MealSlot(str, Enum):
    meal1 = "meal1"
    meal2 = "meal2"
    snack = "snack"
    supplement = "supplement"


class MacroSource(str, Enum):
    database = "database"
    ai_estimated = "ai_estimated"


class FoodItem(BaseModel):
    name: str
    estimated_weight_g: float
    calories_kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    macro_source: MacroSource = MacroSource.ai_estimated


class FoodLogCreate(BaseModel):
    meal_slot: MealSlot
    items: List[FoodItem]
    image_url: Optional[str] = None
    bowl_id: Optional[str] = None
    note: Optional[str] = None


class AnalyzeRequest(BaseModel):
    # For when analysis result comes back and needs macro lookup
    pass


class AnalyzedItem(BaseModel):
    name: str
    estimated_weight_g: float
    source: str = "ai"


class BowlMatch(BaseModel):
    bowl_id: Optional[str] = None
    confidence: float = 0.0
    bowl_name: Optional[str] = None
    tare_weight_g: Optional[float] = None


class FoodAnalysisResponse(BaseModel):
    items: List[AnalyzedItem]
    bowl_match: Optional[BowlMatch] = None
    scale_weight_g: Optional[float] = None
    image_url: str
