"""Per-user food correction learning store.

When a user edits an AI-estimated food log, the delta between the AI's per-gram estimate
and the user's final values is recorded here. On subsequent analysis of the same food,
the stored correction is blended into the AI estimate so the app learns from each user's
personal adjustments.
"""
from pydantic import BaseModel
from typing import Optional


class MacroPerGram(BaseModel):
    cal_per_g: float
    protein_per_g: float
    carbs_per_g: float
    fat_per_g: float


class FoodCorrectionCreate(BaseModel):
    """Schema for the payload when capturing a correction (used internally, not a public endpoint)."""
    name_norm: str
    original_per_g: MacroPerGram
    corrected_per_g: MacroPerGram
