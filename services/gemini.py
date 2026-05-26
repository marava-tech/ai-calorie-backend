"""LLM vision calls via OpenRouter — food analysis, bowl detection, body analysis."""
import asyncio
import base64
import json
import os
import re
from typing import Optional

import httpx

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_VISION_MODEL = os.environ.get("OPENROUTER_VISION_MODEL", "google/gemini-2.0-flash-001")
_TEXT_MODEL = os.environ.get("OPENROUTER_TEXT_MODEL", "google/gemini-2.0-flash-001")


def _api_key() -> str:
    return os.environ["OPENROUTER_API_KEY"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://fitness-backend.marava.tech",
    }


def _img_url(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    b64 = base64.b64encode(image_bytes).decode()
    return f"data:{mime};base64,{b64}"


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


async def _chat(model: str, messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            _OPENROUTER_URL,
            headers=_headers(),
            json={"model": model, "messages": messages},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def analyze_food(image_bytes: bytes) -> dict:
    """Return {items: [{name, estimated_weight_g}], scale_weight_g: float|None}"""
    prompt = (
        "Analyze this food photo. Return ONLY valid JSON in this exact schema:\n"
        '{"items": [{"name": "string", "estimated_weight_g": number}], '
        '"scale_weight_g": number or null}\n'
        "- List every distinct food item visible.\n"
        "- estimated_weight_g: your best estimate for that item's weight in grams.\n"
        "- scale_weight_g: if a kitchen scale display is visible, read the number; otherwise null.\n"
        "Output ONLY the JSON, no other text."
    )
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": _img_url(image_bytes)}},
    ]}]
    text = await _chat(_VISION_MODEL, messages)
    return _parse_json(text)


async def detect_bowl(food_image_bytes: bytes, bowls: list[dict]) -> dict:
    """
    bowls: list of {id, name, tare_weight_g, image_b64}
    Returns {bowl_id, confidence, bowl_name, tare_weight_g} or empty if no match.
    """
    if not bowls:
        return {}

    bowl_desc = "\n".join(f"Bowl {i+1}: {b['name']} (ID: {b['id']})" for i, b in enumerate(bowls))
    prompt = (
        f"I have {len(bowls)} pre-registered bowl presets, followed by a food photo.\n"
        f"Bowl presets:\n{bowl_desc}\n\n"
        "Does the food photo contain one of these bowls?\n"
        "Return ONLY valid JSON:\n"
        '{"matched_bowl_id": "string or null", "confidence": 0.0-1.0, "reason": "string"}\n'
        "Output ONLY the JSON."
    )

    content: list = [{"type": "text", "text": prompt}]
    for b in bowls:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b['image_b64']}"}})
    content.append({"type": "image_url", "image_url": {"url": _img_url(food_image_bytes)}})

    messages = [{"role": "user", "content": content}]
    text = await _chat(_VISION_MODEL, messages)
    result = _parse_json(text)

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


async def analyze_bowl(image_bytes: bytes) -> dict:
    """Returns {description, estimated_tare_weight_g, color, shape, material, size_category}"""
    prompt = (
        "Analyze this bowl/container photo for use as a tare-weight preset in a food tracking app.\n"
        "Return ONLY valid JSON:\n"
        '{"description": "string", "estimated_tare_weight_g": number or null, '
        '"color": "string", "shape": "string", "material": "string", "size_category": "small|medium|large"}\n'
        "- description: concise visual description under 40 words\n"
        "- estimated_tare_weight_g: best estimate of empty weight in grams. "
        "If a scale is visible read it; otherwise estimate from material and size.\n"
        "- size_category: small (<500ml), medium (500-1000ml), large (>1000ml)\n"
        "Output ONLY the JSON."
    )
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": _img_url(image_bytes)}},
    ]}]
    text = await _chat(_VISION_MODEL, messages)
    return _parse_json(text)


async def analyze_body_photo(
    current_image_bytes: bytes,
    prev_image_bytes: Optional[bytes],
    angle: str,
) -> dict:
    """Returns {caption, bf_low_pct, bf_high_pct}"""
    context = "You are analyzing physique photos for body composition tracking. This is a personal fitness tool.\n\n"
    if prev_image_bytes:
        context += "The FIRST image is a previous photo for comparison. The SECOND image is the current photo.\n\n"

    prompt = (
        f"{context}"
        f"Analyze the {angle} view photo. Return ONLY valid JSON:\n"
        '{"bf_low_pct": number, "bf_high_pct": number, "caption": "string"}\n'
        "- bf_low_pct / bf_high_pct: realistic body fat % range estimate\n"
        "- caption: 1-2 sentence objective visual observation\n"
        "Output ONLY the JSON."
    )

    content: list = [{"type": "text", "text": prompt}]
    if prev_image_bytes:
        content.append({"type": "image_url", "image_url": {"url": _img_url(prev_image_bytes)}})
    content.append({"type": "image_url", "image_url": {"url": _img_url(current_image_bytes)}})

    messages = [{"role": "user", "content": content}]
    text = await _chat(_VISION_MODEL, messages)
    return _parse_json(text)


async def estimate_macros(food_name: str, weight_g: float) -> dict:
    """Fallback macro estimation when OpenFoodFacts has no match."""
    prompt = (
        f"Estimate the macros for {weight_g}g of {food_name}. "
        "Return ONLY valid JSON:\n"
        '{"calories_kcal": number, "protein_g": number, "carbs_g": number, "fat_g": number}\n'
        "Output ONLY the JSON."
    )
    messages = [{"role": "user", "content": prompt}]
    text = await _chat(_TEXT_MODEL, messages)
    return _parse_json(text)
