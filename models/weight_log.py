from pydantic import BaseModel


class WeightLogCreate(BaseModel):
    date: str           # YYYY-MM-DD
    weight_kg: float
