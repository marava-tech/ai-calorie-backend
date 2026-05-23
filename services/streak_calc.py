"""Streak calculation — gym, IF, food logging, supplement consistency."""
from datetime import date, timedelta
from database import get_db


async def _consecutive_days(dates: list[str]) -> tuple[int, int]:
    """Returns (current_streak, best_streak) given sorted date strings."""
    if not dates:
        return 0, 0

    unique = sorted(set(dates))
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    best = 1
    current = 1
    for i in range(1, len(unique)):
        prev = date.fromisoformat(unique[i - 1])
        curr = date.fromisoformat(unique[i])
        if (curr - prev).days == 1:
            current += 1
            best = max(best, current)
        else:
            current = 1

    # Reset current streak if last date is not today or yesterday
    if unique[-1] not in (today, yesterday):
        current = 0

    return current, best


async def calculate_all_streaks() -> dict:
    db = get_db()

    # Gym streak
    gym_docs = await db.gym_sessions.find({"attended": True}, {"date": 1}).to_list(None)
    gym_dates = [d["date"] for d in gym_docs]
    gym_current, gym_best = await _consecutive_days(gym_dates)

    # Food logging streak (at least 1 log per day)
    food_docs = await db.food_logs.find({}, {"date": 1}).to_list(None)
    food_dates = list({d["date"] for d in food_docs})
    log_current, log_best = await _consecutive_days(food_dates)

    # IF streak (no food outside window — derived from if_logs)
    if_docs = await db.if_logs.find({"adhered": True}, {"date": 1}).to_list(None)
    if_dates = [d["date"] for d in if_docs]
    if_current, if_best = await _consecutive_days(if_dates)

    # Supplement streak (all required supplements taken)
    supp_docs = await db.supplement_logs.find({}, {"date": 1}).to_list(None)
    supp_dates = list({d["date"] for d in supp_docs})
    supp_current, supp_best = await _consecutive_days(supp_dates)

    return {
        "gym": {"current": gym_current, "best": gym_best},
        "food_logging": {"current": log_current, "best": log_best},
        "intermittent_fasting": {"current": if_current, "best": if_best},
        "supplements": {"current": supp_current, "best": supp_best},
    }
