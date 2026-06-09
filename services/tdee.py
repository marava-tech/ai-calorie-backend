"""TDEE calculation — Mifflin-St Jeor + activity multiplier based on training frequency."""

RECOMP_SURPLUS = 75     # kcal above TDEE
PROTEIN_RATIO = 2.0     # g per kg body weight


def _activity_multiplier(gym_days_per_week: int) -> float:
    """Standard Harris-Benedict activity multipliers by weekly training frequency."""
    if gym_days_per_week <= 1:
        return 1.375   # light activity
    if gym_days_per_week <= 4:
        return 1.55    # moderate (3-4x/week)
    if gym_days_per_week <= 6:
        return 1.725   # very active (5-6x/week)
    return 1.9         # extra active (daily)


def calculate_tdee(
    weight_kg: float,
    height_cm: float,
    age: int,
    sex: str,
    gym_days_per_week: int = 5,
) -> dict:
    # Mifflin-St Jeor BMR
    if sex.lower() == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    tdee = round(bmr * _activity_multiplier(gym_days_per_week))
    goal_kcal = tdee + RECOMP_SURPLUS
    protein_g = round(weight_kg * PROTEIN_RATIO)

    # Remaining kcal split roughly 25% fat / rest carbs
    fat_g = round(goal_kcal * 0.25 / 9)
    carbs_g = round((goal_kcal - protein_g * 4 - fat_g * 9) / 4)

    return {
        "tdee_kcal": tdee,
        "goal_kcal": goal_kcal,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
    }
