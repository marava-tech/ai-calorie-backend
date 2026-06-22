"""Adaptive TDEE calculation from actual intake + weight data.

Instead of relying solely on the Mifflin-St Jeor formula, this module derives the user's
*real* TDEE by reverse-engineering energy balance:

    real_TDEE = avg_intake − (kg_change_per_day × 7700)

If the user is losing weight, their intake is *below* TDEE → real_TDEE > avg_intake.
If gaining, real_TDEE < avg_intake.

Confidence levels:
  high        — ≥14 logged days and ≥6 weight entries spanning ≥14 days
  medium      — ≥10 logged days and ≥4 weight entries spanning ≥10 days
  low         — ≥7 logged days and ≥3 weight entries spanning ≥7 days
  insufficient — below low threshold; no suggestion emitted
"""

from __future__ import annotations
from datetime import date
from typing import Any


# Energy equivalent of 1 kg body mass change (kcal).
_KCAL_PER_KG = 7700.0

# Plateau threshold: weight movement < this (kg/week) for 3+ consecutive weeks
_PLATEAU_KG_PER_WEEK = 0.10

# Minimum calorie differential before suggesting a target change
_MIN_SUGGESTION_DELTA = 50  # kcal


def _linreg_slope(xs: list[float], ys: list[float]) -> float:
    """Simple ordinary-least-squares slope (kcal or kg per unit of x)."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom


def compute_real_tdee(
    intake_by_date: dict[str, float],  # {YYYY-MM-DD: kcal}
    weight_by_date: dict[str, float],  # {YYYY-MM-DD: kg}
    window_days: int = 21,
) -> dict[str, Any]:
    """Estimate real TDEE from logged intake and weight trend.

    Returns a dict with:
        real_tdee_kcal  — estimated TDEE (None when confidence == 'insufficient')
        avg_intake_kcal — mean daily logged intake over window
        kg_per_week     — weight velocity (negative = loss)
        logged_days     — number of logged intake days
        coverage_pct    — fraction of window days with intake logs
        confidence      — 'high' | 'medium' | 'low' | 'insufficient'
        span_days       — days between earliest and latest weight entry
    """
    if not intake_by_date or not weight_by_date:
        return _insufficient(0, 0, 0)

    # Sort and take the most recent `window_days` worth of data
    all_dates = sorted(intake_by_date.keys(), reverse=True)[:window_days]
    windowed_intake = {d: intake_by_date[d] for d in all_dates if d in intake_by_date}

    # Weight entries within the same window
    all_weight_dates = sorted(weight_by_date.keys(), reverse=True)[:window_days]
    windowed_weight = {d: weight_by_date[d] for d in all_weight_dates if d in weight_by_date}

    logged_days = len(windowed_intake)
    weight_entries = len(windowed_weight)

    if logged_days < 7 or weight_entries < 3:
        return _insufficient(logged_days, weight_entries, 0)

    # Span check
    sorted_w_dates = sorted(windowed_weight.keys())
    span_days = (
        date.fromisoformat(sorted_w_dates[-1]) - date.fromisoformat(sorted_w_dates[0])
    ).days

    if span_days < 7:
        return _insufficient(logged_days, weight_entries, span_days)

    # Convert weight dates to numeric x (days since earliest)
    origin = date.fromisoformat(sorted_w_dates[0])
    wx = [(date.fromisoformat(d) - origin).days for d in sorted_w_dates]
    wy = [windowed_weight[d] for d in sorted_w_dates]
    slope_kg_per_day = _linreg_slope(wx, wy)
    kg_per_week = round(slope_kg_per_day * 7, 3)

    avg_intake = sum(windowed_intake.values()) / logged_days
    coverage_pct = round(logged_days / window_days * 100, 1)

    # real_TDEE = avg_intake - (slope_kg_per_day × 7700)
    real_tdee = avg_intake - slope_kg_per_day * _KCAL_PER_KG

    # Confidence thresholds
    if logged_days >= 14 and weight_entries >= 6 and span_days >= 14:
        confidence = "high"
    elif logged_days >= 10 and weight_entries >= 4 and span_days >= 10:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "real_tdee_kcal": round(real_tdee),
        "avg_intake_kcal": round(avg_intake),
        "kg_per_week": kg_per_week,
        "logged_days": logged_days,
        "coverage_pct": coverage_pct,
        "span_days": span_days,
        "weight_entries": weight_entries,
        "confidence": confidence,
    }


def _insufficient(logged_days: int, weight_entries: int, span_days: int) -> dict:
    return {
        "real_tdee_kcal": None,
        "avg_intake_kcal": None,
        "kg_per_week": None,
        "logged_days": logged_days,
        "coverage_pct": 0.0,
        "span_days": span_days,
        "weight_entries": weight_entries,
        "confidence": "insufficient",
    }


def detect_plateau(weekly_avgs: list[dict]) -> bool:
    """Return True if weight has been stalling for 3+ consecutive ISO weeks.

    weekly_avgs should be a list of {week_start, avg_weight} dicts, most-recent last.
    Requires at least 3 entries with non-None avg_weight.
    """
    valid = [w for w in weekly_avgs if w.get("avg_weight") is not None]
    if len(valid) < 3:
        return False
    recent = valid[-3:]
    weights = [float(w["avg_weight"]) for w in recent]
    # Check all week-over-week deltas are within plateau threshold
    for i in range(1, len(weights)):
        if abs(weights[i] - weights[i - 1]) >= _PLATEAU_KG_PER_WEEK:
            return False
    return True


def build_suggestion(
    insight: dict,
    profile: dict,
    is_plateau: bool = False,
) -> dict:
    """Given a compute_real_tdee result and the user's profile, build a goal suggestion.

    Returns:
        type            — 'adopt_tdee' | 'plateau_adjust' | 'none'
        message         — human-readable explanation
        suggested_goal_kcal — proposed new daily target (None when type == 'none')
        delta_kcal      — difference from current goal (signed)
    """
    confidence = insight.get("confidence", "insufficient")
    real_tdee = insight.get("real_tdee_kcal")
    current_goal = profile.get("goal_kcal") or 0

    if confidence == "insufficient" or real_tdee is None:
        return {"type": "none", "message": "Not enough data yet.", "suggested_goal_kcal": None, "delta_kcal": 0}

    delta = real_tdee - current_goal
    kg_per_week = insight.get("kg_per_week", 0.0) or 0.0

    if is_plateau and abs(kg_per_week) < _PLATEAU_KG_PER_WEEK:
        # Weight has stalled — nudge by −80 kcal to restart deficit
        new_goal = current_goal - 80
        msg = (
            f"Your weight has been flat for 3+ weeks (< {_PLATEAU_KG_PER_WEEK} kg/week movement). "
            f"Drop your daily target by 80 kcal to reignite the deficit?"
        )
        return {
            "type": "plateau_adjust",
            "message": msg,
            "suggested_goal_kcal": new_goal,
            "delta_kcal": -80,
        }

    if abs(delta) < _MIN_SUGGESTION_DELTA:
        return {"type": "none", "message": "Your targets are on track.", "suggested_goal_kcal": None, "delta_kcal": round(delta)}

    direction = "higher" if delta > 0 else "lower"
    kg_dir = "losing" if kg_per_week < 0 else "gaining"
    msg = (
        f"Based on {insight['logged_days']} logged days and {insight['weight_entries']} weigh-ins, "
        f"your real TDEE looks like ~{real_tdee} kcal "
        f"(you're {kg_dir} {abs(kg_per_week):.2f} kg/week). "
        f"Your current target of {current_goal} kcal is {abs(round(delta))} kcal {direction} — "
        f"apply the data-derived target?"
    )
    return {
        "type": "adopt_tdee",
        "message": msg,
        "suggested_goal_kcal": round(real_tdee),
        "delta_kcal": round(delta),
    }
