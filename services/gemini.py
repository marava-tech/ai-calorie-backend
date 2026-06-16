"""LLM vision calls via OpenRouter — food analysis, body analysis."""
import base64
import json
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# gemini-2.5-pro for vision (best accuracy); gemini-2.5-flash for text (fast + cheap)
_VISION_MODEL = os.environ.get("OPENROUTER_VISION_MODEL", "google/gemini-2.5-pro")
_TEXT_MODEL = os.environ.get("OPENROUTER_TEXT_MODEL", "google/gemini-2.5-flash")


def _img_url(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    b64 = base64.b64encode(image_bytes).decode()
    return f"data:{mime};base64,{b64}"


def _parse_json(text: str | None) -> dict:
    if not text:
        raise ValueError("LLM returned an empty response")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # LLM sometimes returns truncated output — extract the first valid JSON object
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


async def _chat(model: str, messages: list[dict], api_key: str, system: str | None = None, max_tokens: int | None = None) -> str:
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://fitness-backend.marava.tech",
    }
    payload: dict = {"model": model, "messages": messages}
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages
    if max_tokens:
        payload["max_tokens"] = max_tokens
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(_OPENROUTER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


_FOOD_SYSTEM = (
    "You are an expert nutritionist and food analyst trained on professional dietary databases "
    "(USDA FoodData Central, NCCDB). You specialize in visual food identification and accurate "
    "portion weight estimation from photos. Your estimates are used for health tracking, so "
    "precision matters — always err on the side of slight overestimation rather than under."
)

_FOOD_ANALYZE_PROMPT = """Analyze this food photo with high precision. Identify every distinct food item visible.

Weight estimation guidelines:
- Reference: standard dinner plate ≈ 26cm diameter, side plate ≈ 20cm, standard bowl ≈ 400–600ml
- Common anchors: cooked rice (1 cup ≈ 200g), chicken breast (medium ≈ 160g), bread slice ≈ 30g, egg ≈ 55g, banana (medium ≈ 120g)
- For Indian food: 1 roti ≈ 40g, 1 cup dal ≈ 250g, 1 cup sabzi ≈ 200g, 1 serving rice ≈ 150–200g
- Factor in cooking method: fried items are denser, boiled/steamed have more water weight

Scale reading rules (CRITICAL):
- If a kitchen scale display is visible, read that number and put it in scale_weight_g
- scale_weight_g is the GROSS weight = food + bowl/plate/container combined
- Do NOT use the scale reading as a food item's estimated_weight_g — that field must always be a visual estimate
- estimated_weight_g per item is your visual portion estimate, independent of any scale reading

Naming rules:
- Be specific: "grilled chicken breast" not "chicken", "steamed basmati rice" not "rice"
- List composite dishes as one item (e.g., "paneer butter masala") — do NOT break into individual ingredients
- Include preparation: "deep-fried samosa", "boiled egg", "raw cucumber slices"

Return ONLY valid JSON, no explanation, no markdown:
{"items": [{"name": "string", "estimated_weight_g": number}], "scale_weight_g": number or null}"""


async def analyze_food(image_bytes: bytes, api_key: str) -> dict:
    """Return {items: [{name, estimated_weight_g}], scale_weight_g: float|None}"""
    messages = [{"role": "user", "content": [
        {"type": "text", "text": _FOOD_ANALYZE_PROMPT},
        {"type": "image_url", "image_url": {"url": _img_url(image_bytes)}},
    ]}]
    text = await _chat(_VISION_MODEL, messages, api_key=api_key, system=_FOOD_SYSTEM)
    return _parse_json(text)


_BODY_SYSTEM = (
    "You are a certified physique assessment specialist with expertise in visual body composition analysis. "
    "You provide objective, calibrated body fat percentage estimates based on visible muscle definition, "
    "subcutaneous fat distribution, vascularity, and skin fold appearance. Your assessments are used for "
    "fitness progress tracking — be accurate and consistent, not flattering."
)


async def analyze_body_photo(
    current_image_bytes: bytes,
    prev_image_bytes: Optional[bytes],
    angle: str,
    api_key: str,
) -> dict:
    """Returns {caption, bf_low_pct, bf_high_pct}"""
    comparison_note = (
        "The FIRST image is a previous reference photo. The SECOND image is the current photo being assessed. "
        "Note any visible changes in muscle fullness, fat distribution, or definition.\n\n"
        if prev_image_bytes else ""
    )

    prompt = (
        f"{comparison_note}"
        f"Assess the {angle} view for body composition.\n\n"
        "Body fat % visual reference:\n"
        "  Male: 3–5% (competition shredded), 6–9% (visible abs + striations), 10–14% (abs visible), "
        "15–19% (soft abs), 20–25% (no definition), 25%+ (significant fat cover)\n"
        "  Female: 10–13% (athlete), 14–17% (fitness), 18–24% (average fit), 25–31% (average), 32%+ (above average)\n\n"
        "Evaluate: visible muscle separation, abdominal definition, vascularity, subcutaneous fat "
        "at waist/hips/chest/arms, overall body proportions.\n\n"
        "Return ONLY valid JSON:\n"
        '{"bf_low_pct": number, "bf_high_pct": number, "caption": "string"}\n\n'
        "- bf_low_pct / bf_high_pct: realistic ±2–3% range (e.g., 14 and 17)\n"
        "- caption: 2–3 sentences of objective observations (muscle groups visible, fat distribution, "
        "any notable changes if comparison photo present)\n"
        "Output ONLY the JSON."
    )

    content: list = [{"type": "text", "text": prompt}]
    if prev_image_bytes:
        content.append({"type": "image_url", "image_url": {"url": _img_url(prev_image_bytes)}})
    content.append({"type": "image_url", "image_url": {"url": _img_url(current_image_bytes)}})

    messages = [{"role": "user", "content": content}]
    text = await _chat(_VISION_MODEL, messages, api_key=api_key, system=_BODY_SYSTEM)
    return _parse_json(text)


_COMPARE_SYSTEM = (
    "You are an elite physique coach and certified body composition analyst. "
    "You specialize in tracking visual progress over time using photographic evidence. "
    "Your assessments are objective, detailed, and actionable — not motivational fluff."
)


async def compare_body_photos(photos: list[dict], api_key: str) -> dict:
    """
    Compare 2–3 body photos chronologically.
    Each dict: {image_bytes: bytes, date: str, angle: str}
    Returns structured comparison JSON.
    """
    photos_sorted = sorted(photos, key=lambda p: p["date"])
    n = len(photos_sorted)
    first_date = photos_sorted[0]["date"]
    last_date = photos_sorted[-1]["date"]
    angle = photos_sorted[0]["angle"]

    from datetime import date as dt_date
    try:
        d1 = dt_date.fromisoformat(first_date)
        d2 = dt_date.fromisoformat(last_date)
        duration_days = (d2 - d1).days
    except Exception:
        duration_days = 0

    photo_labels = "\n".join(
        f"  Photo {i+1}: {p['date']}" for i, p in enumerate(photos_sorted)
    )

    prompt = (
        f"You are given {n} {angle}-view body photos taken in chronological order:\n"
        f"{photo_labels}\n\n"
        f"Total duration: {duration_days} days ({duration_days // 7} weeks)\n\n"
        "Analyze the visual progression across ALL photos. Compare muscle definition, "
        "fat distribution, vascularity, posture, and overall body composition changes.\n\n"
        "Then assess: given the duration, what progress was realistically EXPECTED for someone "
        "doing consistent training and diet? Are the results ahead, on track, or behind expectations?\n\n"
        "Return ONLY valid JSON in this exact structure:\n"
        "{\n"
        '  "duration_days": number,\n'
        '  "overall": "improved" | "maintained" | "declined",\n'
        '  "improvements": ["specific observation 1", "..."],\n'
        '  "deimprovements": ["specific observation 1", "..."],\n'
        '  "bf_estimate_latest": "e.g. 14–17%",\n'
        '  "expected_in_duration": "What typical progress looks like in this timeframe",\n'
        '  "verdict": "Are results ahead / on track / behind expectations — 1–2 sentences",\n'
        '  "suggestions": ["actionable suggestion 1", "actionable suggestion 2", "..."]\n'
        "}\n\n"
        "Rules:\n"
        "- improvements and deimprovements: specific, observable, body-part-level detail\n"
        "- If no visible change in an area, omit it\n"
        "- suggestions: 3–5 concrete, prioritized actions\n"
        "- Output ONLY the JSON, no markdown fences"
    )

    content: list = [{"type": "text", "text": prompt}]
    for p in photos_sorted:
        content.append({"type": "image_url", "image_url": {"url": _img_url(p["image_bytes"])}})

    messages = [{"role": "user", "content": content}]
    text = await _chat(_VISION_MODEL, messages, api_key=api_key, system=_COMPARE_SYSTEM)
    result = _parse_json(text)
    result["duration_days"] = duration_days
    result["first_date"] = first_date
    result["last_date"] = last_date
    return result


_MACRO_SYSTEM = (
    "You are a registered dietitian with expert-level knowledge of food composition databases "
    "(USDA FoodData Central, NCCDB, Indian Food Composition Tables). "
    "Provide accurate macronutrient values scaled to the exact weight given. "
    "Use the most common preparation method if unspecified. Return precise numbers, not estimates rounded to 5s."
)

_MACRO_PROMPT_TEMPLATE = (
    "Calculate macros for {weight_g}g of {food_name}.\n\n"
    "Steps:\n"
    "1. Identify the standard per-100g values from nutritional databases\n"
    "2. Scale proportionally to {weight_g}g\n"
    "3. Account for cooking method if specified in the name\n\n"
    "Return ONLY valid JSON:\n"
    '{{"calories_kcal": number, "protein_g": number, "carbs_g": number, "fat_g": number}}\n\n'
    "Output ONLY the JSON, no explanation."
)


async def estimate_macros(food_name: str, weight_g: float, api_key: str) -> dict:
    """Fallback macro estimation when OpenFoodFacts has no match."""
    prompt = _MACRO_PROMPT_TEMPLATE.format(food_name=food_name, weight_g=weight_g)
    messages = [{"role": "user", "content": prompt}]
    text = await _chat(_TEXT_MODEL, messages, api_key=api_key, system=_MACRO_SYSTEM, max_tokens=200)
    return _parse_json(text)
