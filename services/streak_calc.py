"""Streak calculation — gym, IF, food logging, supplement consistency."""
from datetime import date, timedelta
from database import get_db


async def consecutive_days(dates: list[str]) -> tuple[int, int]:
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

    if unique[-1] not in (today, yesterday):
        current = 0

    return current, best


async def calculate_all_streaks() -> dict:
    db = get_db()

    gym_docs = await db.gym_sessions.find({"attended": True}, {"date": 1}).to_list(None)
    gym_current, gym_best = await consecutive_days([d["date"] for d in gym_docs])

    food_docs = await db.food_logs.find({}, {"date": 1}).to_list(None)
    log_current, log_best = await consecutive_days(list({d["date"] for d in food_docs}))

    if_docs = await db.if_logs.find({"adhered": True}, {"date": 1}).to_list(None)
    if_current, if_best = await consecutive_days([d["date"] for d in if_docs])

    supp_docs = await db.supplement_logs.find({}, {"date": 1}).to_list(None)
    supp_current, supp_best = await consecutive_days(list({d["date"] for d in supp_docs}))

    return {
        "gym": {"current": gym_current, "best": gym_best},
        "food_logging": {"current": log_current, "best": log_best},
        "intermittent_fasting": {"current": if_current, "best": if_best},
        "supplements": {"current": supp_current, "best": supp_best},
    }
