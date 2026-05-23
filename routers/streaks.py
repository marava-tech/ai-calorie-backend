"""Streak aggregation endpoint."""
from fastapi import APIRouter, Depends
from auth import get_current_user
from services.streak_calc import calculate_all_streaks

router = APIRouter(prefix="/api/streaks", tags=["streaks"])


@router.get("")
async def get_streaks(_: str = Depends(get_current_user)):
    return await calculate_all_streaks()
