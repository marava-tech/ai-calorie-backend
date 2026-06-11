"""Streak calculation — gym (weekly window), IF, food logging, supplement consistency."""
from datetime import date, datetime, timedelta, timezone
from database import get_db


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


async def consecutive_days(dates: list[str]) -> tuple[int, int]:
    """Returns (current_streak, best_streak) given sorted date strings."""
    if not dates:
        return 0, 0

    unique = sorted(set(dates))
    today = _utc_today().isoformat()
    yesterday = (_utc_today() - timedelta(days=1)).isoformat()

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


async def consecutive_gym_days_with_skip(dates: list[str], max_skip: int = 2) -> tuple[int, int]:
    """
    Returns (current_streak, best_streak) for gym visits, counting each attended day.
    A gap of up to max_skip rest days between sessions is allowed and does not break the streak.
    Example: Mon gym → Tue/Wed rest → Thu gym  = gap of 2 = still one streak of 2 days.
    """
    if not dates:
        return 0, 0

    unique = sorted(set(dates))
    today = _utc_today()
    last_date = date.fromisoformat(unique[-1])
    days_since_last = (today - last_date).days

    # ── best streak (forward scan) ──────────────────────────────────────────
    best = 1
    run = 1
    for i in range(1, len(unique)):
        prev = date.fromisoformat(unique[i - 1])
        curr = date.fromisoformat(unique[i])
        # gap in calendar days between two sessions; 1 = consecutive, 2+ = rest days in between
        calendar_gap = (curr - prev).days
        if calendar_gap <= max_skip + 1:   # e.g. max_skip=2 → allow gaps ≤ 3 days apart
            run += 1
            best = max(best, run)
        else:
            run = 1
    best = max(best, 1)

    # ── current streak (backward scan from last session) ───────────────────
    # Streak is broken only if the gap from today to the last session exceeds
    # the same threshold used between sessions (max_skip + 1 calendar days).
    if days_since_last > max_skip + 1:
        return 0, best

    current = 1
    for i in range(len(unique) - 1, 0, -1):
        curr = date.fromisoformat(unique[i])
        prev = date.fromisoformat(unique[i - 1])
        calendar_gap = (curr - prev).days
        if calendar_gap <= max_skip + 1:
            current += 1
        else:
            break

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

    today = _utc_today()
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


async def calculate_all_streaks(user_id: str) -> dict:
    db = get_db()

    profile = await db.user_profile.find_one({"user_id": user_id})
    min_days = (profile or {}).get("gym_streak_min_days_per_week", 5)

    # Gym attendance comes from daily check-ins (gym: True), not gym_sessions
    # (gym_sessions is used for progress photos, not attendance tracking)
    gym_docs = await db.daily_checkins.find({"gym": True, "user_id": user_id}, {"date": 1}).to_list(None)
    gym_date_list = [d["date"] for d in gym_docs]
    gym_weekly = await calculate_weekly_gym_streak(gym_date_list, min_days)

    # Day-based streak with 2-day skip tolerance (shown in the main chip)
    gym_days_current, gym_days_best = await consecutive_gym_days_with_skip(gym_date_list, max_skip=2)
    gym_weekly["current_days"] = gym_days_current
    gym_weekly["best_days"] = gym_days_best

    food_docs = await db.food_logs.find({"user_id": user_id}, {"date": 1}).to_list(None)
    log_current, log_best = await consecutive_days(list({d["date"] for d in food_docs}))

    if_docs = await db.daily_checkins.find({"if_followed": True, "user_id": user_id}, {"date": 1}).to_list(None)
    if_current, if_best = await consecutive_days([d["date"] for d in if_docs])

    # Supplement streak: any checkin that has at least one supplement_entry with taken=True
    supp_docs = await db.daily_checkins.find(
        {"supplement_entries": {"$elemMatch": {"taken": True}}, "user_id": user_id},
        {"date": 1},
    ).to_list(None)
    supp_current, supp_best = await consecutive_days(list({d["date"] for d in supp_docs}))

    return {
        "gym_weekly": gym_weekly,
        "food_logging": {"current": log_current, "best": log_best},
        "intermittent_fasting": {"current": if_current, "best": if_best},
        "supplements": {"current": supp_current, "best": supp_best},
    }
