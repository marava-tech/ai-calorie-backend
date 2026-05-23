"""Gemini Flash vision calls — food analysis, bowl detection, body analysis."""
import os
import base64
import json
import re
from typing import Optional
import google.generativeai as genai

_model: genai.GenerativeModel | None = None


def _get_model() -> genai.GenerativeModel:
    global _model
    if _model is None:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        _model = genai.GenerativeModel("gemini-1.5-flash")
    return _model


def _image_part(image_bytes: bytes, mime: str = "image/jpeg") -> dict:
    return {"mime_type": mime, "data": base64.b64encode(image_bytes).decode()}


async def analyze_food(image_bytes: bytes) -> dict:
    """Return {items: [{name, estimated_weight_g}], scale_weight_g: float|None}"""
    prompt = (
        "Analyze this food photo. Return ONLY valid JSON in this exact schema:\n"
        '{"items": [{"name": "string", "estimated_weight_g": number}], '
        '"scale_weight_g": number or null}\n'
        "- List every distinct food item visible.\n"
        "- estimated_weight_g: your best estimate for that item's weight in grams.\n"
        "- scale_weight_g: if a kitchen scale display is visible, read the number shown; "
        "otherwise null.\n"
        "Output ONLY the JSON, no other text."
    )
    model = _get_model()
    response = model.generate_content([prompt, _image_part(image_bytes)])
    text = response.text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


async def detect_bowl(food_image_bytes: bytes, bowls: list[dict]) -> dict:
    """
    bowls: list of {id, name, tare_weight_g, image_bytes (b64 encoded)}
    Returns {bowl_id, confidence, bowl_name, tare_weight_g} or empty if no match.
    """
    if not bowls:
        return {}

    parts = []
    bowl_desc = []
    for i, b in enumerate(bowls):
        label = f"Bowl {i+1}: {b['name']} (ID: {b['id']})"
        bowl_desc.append(label)
        parts.append(f"\n{label}:")
        img_bytes = base64.b64decode(b["image_b64"])
        parts.append(_image_part(img_bytes))

    bowl_list = "\n".join(bowl_desc)
    prompt = (
        f"I have {len(bowls)} pre-registered bowl presets shown above, followed by a food photo.\n"
        f"Bowl presets:\n{bowl_list}\n\n"
        "Look at the LAST image (the food photo). Does it contain one of these bowls?\n"
        "Return ONLY valid JSON:\n"
        '{"matched_bowl_id": "string or null", "confidence": 0.0-1.0, "reason": "string"}\n'
        "- matched_bowl_id: the ID of the matching bowl, or null if none found.\n"
        "- confidence: how confident you are (0.0-1.0).\n"
        "Output ONLY the JSON."
    )

    content = [prompt]
    content.extend(parts)
    content.append(_image_part(food_image_bytes))

    model = _get_model()
    response = model.generate_content(content)
    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    result = json.loads(text)

    matched_id = result.get("matched_bowl_id")
    confidence = float(result.get("confidence", 0.0))

    if matched_id and confidence >= 0.6:
        matched = next((b for b in bowls if b["id"] == matched_id), None)
        if matched:
            return {
                "bowl_id": matched_id,
                "confidence": confidence,
                "bowl_name": matched["name"],
                "tare_weight_g": matched["tare_weight_g"],
            }
    return {}


async def describe_bowl(image_bytes: bytes) -> str:
    """Generate a visual description for a bowl reference photo."""
    prompt = (
        "Describe this bowl/container concisely for identification purposes. "
        "Mention: shape, color, size, any distinctive markings. "
        "Keep it under 40 words. Output ONLY the description text."
    )
    model = _get_model()
    response = model.generate_content([prompt, _image_part(image_bytes)])
    return response.text.strip()


async def analyze_body_photo(
    current_image_bytes: bytes,
    prev_image_bytes: Optional[bytes],
    angle: str,
) -> dict:
    """
    Returns {caption, bf_low_pct, bf_high_pct}
    """
    parts = [current_image_bytes]
    if prev_image_bytes:
        parts.insert(0, prev_image_bytes)

    context = (
        "You are analyzing physique photos for body composition tracking. "
        "This is a personal fitness tool.\n\n"
    )
    if prev_image_bytes:
        context += (
            "The FIRST image is a previous photo from the same angle for comparison. "
            "The SECOND image is the current photo being analyzed.\n\n"
        )

    prompt = (
        f"{context}"
        f"Analyze the {angle} view photo. Provide:\n"
        "1. Estimated body fat % range (realistic, not flattering)\n"
        "2. Brief visual observations (muscle definition, changes vs previous if available)\n\n"
        "Return ONLY valid JSON:\n"
        '{"bf_low_pct": number, "bf_high_pct": number, "caption": "string"}\n'
        "- bf_low_pct / bf_high_pct: numeric body fat % range estimate\n"
        "- caption: 1-2 sentence visual observation, objective tone\n"
        "Output ONLY the JSON."
    )

    model = _get_model()
    content = [prompt] + [_image_part(b) for b in parts]
    response = model.generate_content(content)
    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


async def estimate_macros(food_name: str, weight_g: float) -> dict:
    """Fallback macro estimation when OpenFoodFacts has no match."""
    prompt = (
        f"Estimate the macros for {weight_g}g of {food_name}. "
        "Return ONLY valid JSON:\n"
        '{"calories_kcal": number, "protein_g": number, "carbs_g": number, "fat_g": number}\n'
        "Output ONLY the JSON."
    )
    model = _get_model()
    response = model.generate_content([prompt])
    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)
