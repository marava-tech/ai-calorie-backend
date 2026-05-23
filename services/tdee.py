"""TDEE calculation — Mifflin-St Jeor + Very Active multiplier (1.725)."""

ACTIVITY_MULTIPLIER = 1.725   # 5x/week gym
RECOMP_SURPLUS = 75           # kcal above TDEE
PROTEIN_RATIO = 2.0           # g per kg body weight


def calculate_tdee(weight_kg: float, height_cm: float, age: int, sex: str) -> dict:
    # Mifflin-St Jeor BMR
    if sex.lower() == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    tdee = round(bmr * ACTIVITY_MULTIPLIER)
    goal_kcal = tdee + RECOMP_SURPLUS
    protein_g = round(weight_kg * PROTEIN_RATIO)

    # Remaining kcal split roughly 30% fat / rest carbs
    fat_g = round(goal_kcal * 0.25 / 9)
    carbs_g = round((goal_kcal - protein_g * 4 - fat_g * 9) / 4)

    return {
        "tdee_kcal": tdee,
        "goal_kcal": goal_kcal,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
    }
