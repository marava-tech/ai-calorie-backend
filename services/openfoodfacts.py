"""OpenFoodFacts macro lookup — fallback to Gemini if not found."""
import httpx
from typing import Optional


OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"


async def lookup_macros(food_name: str, weight_g: float) -> Optional[dict]:
    """
    Returns macros scaled to weight_g, or None if not found.
    Result: {calories_kcal, protein_g, carbs_g, fat_g, source: "database"}
    """
    params = {
        "search_terms": food_name,
        "json": 1,
        "page_size": 5,
        "fields": "nutriments,product_name",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(OFF_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    products = data.get("products", [])
    for product in products:
        n = product.get("nutriments", {})
        cal = n.get("energy-kcal_100g") or n.get("energy_100g", 0)
        protein = n.get("proteins_100g", 0)
        carbs = n.get("carbohydrates_100g", 0)
        fat = n.get("fat_100g", 0)

        if cal and protein is not None:
            ratio = weight_g / 100.0
            return {
                "calories_kcal": round(cal * ratio, 1),
                "protein_g": round(protein * ratio, 1),
                "carbs_g": round(carbs * ratio, 1),
                "fat_g": round(fat * ratio, 1),
                "source": "database",
            }
    return None
