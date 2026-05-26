"""Streak calculation — gym (weekly window), IF, food logging, supplement consistency."""
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


def _iso_week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _monday_of_key(key: str) -> date:
    year, week = key.split("-W")
    return date.fromisocalendar(int(year), int(week), 1)


async def calculate_weekly_gym_streak(gym_dates: list[str], min_days: int) -> dict:
    """
    Gym streak counted in ISO weeks (Mon–Sun).
    A week passes when attended >= min_days days.
    Returns {current_weeks, best_weeks, current_week_days}.
    """
    if not gym_dates:
        return {"current_weeks": 0, "best_weeks": 0, "current_week_days": 0}

    week_counts: dict[str, int] = {}
    for ds in gym_dates:
        d = date.fromisoformat(ds)
        key = _iso_week_key(d)
        week_counts[key] = week_counts.get(key, 0) + 1

    today = date.today()
    current_week_key = _iso_week_key(today)
    current_week_days = week_counts.get(current_week_key, 0)

    completed_weeks = sorted(k for k in week_counts if k != current_week_key)
    passing = {k for k in completed_weeks if week_counts[k] >= min_days}

    # Best streak
    best = 0
    run = 0
    for k in completed_weeks:
        if k in passing:
            run += 1
            best = max(best, run)
        else:
            run = 0

    # Current streak — walk backwards from most recent completed week
    current = 0
    if completed_weeks:
        last_key = completed_weeks[-1]
        last_monday = _monday_of_key(last_key)
        this_monday = today - timedelta(days=today.weekday())
        prev_monday = this_monday - timedelta(weeks=1)

        if last_monday < prev_monday:
            current = 0
        else:
            check_monday = last_monday
            while True:
                check_key = _iso_week_key(check_monday)
                if check_key not in passing:
                    break
                current += 1
                check_monday -= timedelta(weeks=1)

    return {
        "current_weeks": current,
        "best_weeks": best,
        "current_week_days": current_week_days,
    }


async def calculate_all_streaks() -> dict:
    db = get_db()

    profile = await db.user_profile.find_one({})
    min_days = (profile or {}).get("gym_streak_min_days_per_week", 5)

    gym_docs = await db.gym_sessions.find({"attended": True}, {"date": 1}).to_list(None)
    gym_weekly = await calculate_weekly_gym_streak([d["date"] for d in gym_docs], min_days)

    food_docs = await db.food_logs.find({}, {"date": 1}).to_list(None)
    log_current, log_best = await consecutive_days(list({d["date"] for d in food_docs}))

    if_docs = await db.daily_checkins.find({"if_followed": True}, {"date": 1}).to_list(None)
    if_current, if_best = await consecutive_days([d["date"] for d in if_docs])

    supp_docs = await db.daily_checkins.find(
        {"$or": [
            {"fish_oil": True},
            {"magnesium": True},
            {"vitamin_d3": True},
            {"multi_vitamin": True},
            {"whey_protein": True},
        ]},
        {"date": 1},
    ).to_list(None)
    supp_current, supp_best = await consecutive_days(list({d["date"] for d in supp_docs}))

    return {
        "gym_weekly": gym_weekly,
        "food_logging": {"current": log_current, "best": log_best},
        "intermittent_fasting": {"current": if_current, "best": if_best},
        "supplements": {"current": supp_current, "best": supp_best},
    }
