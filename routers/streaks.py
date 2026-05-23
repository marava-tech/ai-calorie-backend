"""Streak aggregation endpoint."""
from fastapi import APIRouter, Depends
from auth import verify_api_key
from services.streak_calc import calculate_all_streaks

router = APIRouter(prefix="/api/streaks", tags=["streaks"])


@router.get("")
async def get_streaks(_: str = Depends(verify_api_key)):
    return await calculate_all_streaks()
