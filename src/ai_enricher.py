import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv()

# ── Auth 
_api_key = os.getenv("GEMINI_API_KEY")
if not _api_key:
    raise EnvironmentError(
        "GEMINI_API_KEY not found. "
        "Copy .env.example → .env and fill in your key."
    )

client = genai.Client(api_key=_api_key)

# ── Constants 
MODEL = "gemini-2.5-flash"          # stable, fast, free-tier friendly
                                     # (gemini-2.0-flash was retired by Google
                                     # on 2026-06-01 — update here if Google
                                     # retires this one too; see
                                     # https://ai.google.dev/gemini-api/docs/models)
MAX_RETRIES = 3

MATERIALS = [
    "grass_lush",
    "safety_rubber_red",
    "safety_rubber_blue",
    "safety_rubber_green",
    "fine_sand",
    "wood_chips",
    "asphalt_dark",
    "concrete_light",
    "gravel_gray",
    "water_feature",
]

SYSTEM_PROMPT = """You are a Landscape Architect AI assistant.
Your sole job is to classify playground / park surfaces into named materials.
Always respond with a valid JSON array and nothing else — no markdown fences,
no explanation, no extra keys."""

USER_PROMPT_TEMPLATE = """Classify each surface below into one of these materials:
{materials}

Heuristics:
- Large green RGB → grass_lush
- Bright red RGB in small areas → safety_rubber_red
- Bright blue RGB → safety_rubber_blue
- Beige / pale yellow, small area → fine_sand or wood_chips
- Dark gray, large area → asphalt_dark
- Light gray → concrete_light
- Very light blue, irregular shape → water_feature

Surface data (id, rgb 0-1 floats, area in px²):
{data}

Return ONLY a JSON array, one object per surface:
[{{"id": 0, "material": "grass_lush", "confidence": "high"}}, ...]
confidence must be "high", "medium", or "low"."""


def _call_gemini(payload: str) -> list[dict]:
    """Call Gemini and return parsed JSON list. Retries on transient errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=payload,
                config={"system_instruction": SYSTEM_PROMPT},
            )
            raw = response.text.strip()
            # Belt-and-suspenders strip of any accidental fences
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw)

        except json.JSONDecodeError as e:
            print(f"[AI] Parse error (attempt {attempt}/{MAX_RETRIES}): {e}")
            print(f"[AI] Raw response was: {response.text[:300]}")
        except Exception as e:
            print(f"[AI] API error (attempt {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)   # exponential back-off

    return []


def _fallback_classify(color: list[float]) -> str:
    """Rule-based fallback when AI is unavailable."""
    r, g, b = (color + [0, 0, 0])[:3]
    if g > 0.35 and g > r and g > b:
        return "grass_lush"
    if r > 0.5 and g < 0.3 and b < 0.3:
        return "safety_rubber_red"
    if b > 0.5 and r < 0.3:
        return "safety_rubber_blue"
    if r > 0.6 and g > 0.5 and b < 0.3:
        return "fine_sand"
    if r < 0.25 and g < 0.25 and b < 0.25:
        return "asphalt_dark"
    return "concrete_light"


def enrich_surfaces(input_file: str, output_file: str) -> dict:
    """
    Read *input_file*, classify surfaces via Gemini, write *output_file*.
    Returns analytics dict with per-material area totals.
    """
    t0 = time.perf_counter()

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    surfaces = data.get("surfaces", [])
    if not surfaces:
        print("[AI] No surfaces found — skipping enrichment.")
        return {}

    # Build compact payload for Gemini
    surface_context = [
        {"id": i, "rgb": s.get("color"), "area": round(s.get("area", 0))}
        for i, s in enumerate(surfaces)
    ]

    prompt = USER_PROMPT_TEMPLATE.format(
        materials=", ".join(MATERIALS),
        data=json.dumps(surface_context, separators=(",", ":")),
    )

    print(f"[AI] Sending {len(surfaces)} surfaces to Gemini ({MODEL})…")
    enrichment_map = _call_gemini(prompt)

    # ── Apply results 
    applied = 0
    if enrichment_map:
        for entry in enrichment_map:
            idx = entry.get("id")
            mat = entry.get("material")
            if isinstance(idx, int) and 0 <= idx < len(surfaces) and mat in MATERIALS:
                surfaces[idx]["material_type"] = mat
                surfaces[idx]["ai_confidence"] = entry.get("confidence", "low")
                applied += 1
        print(f"[AI] Applied AI classification to {applied}/{len(surfaces)} surfaces.")
    else:
        print("[AI] Falling back to rule-based classification.")

    # Fill any gaps with rule-based fallback
    for s in surfaces:
        if "material_type" not in s:
            s["material_type"] = _fallback_classify(s.get("color", []))
            s["ai_confidence"] = "fallback"

    # ── Per-material analytics 
    material_stats: dict[str, dict] = {}
    for s in surfaces:
        mat = s["material_type"]
        if mat not in material_stats:
            material_stats[mat] = {"count": 0, "total_area_px2": 0.0}
        material_stats[mat]["count"] += 1
        material_stats[mat]["total_area_px2"] += s.get("area", 0)

    # Round areas for readability
    for mat in material_stats:
        material_stats[mat]["total_area_px2"] = round(
            material_stats[mat]["total_area_px2"], 1
        )

    enrichment_analytics = {
        "model_used": MODEL,
        "surfaces_total": len(surfaces),
        "surfaces_ai_classified": applied,
        "surfaces_fallback": len(surfaces) - applied,
        "material_breakdown": material_stats,
        "enrichment_time_s": round(time.perf_counter() - t0, 3),
    }

    # Merge analytics back into data
    if "analytics" not in data:
        data["analytics"] = {}
    data["analytics"].update(enrichment_analytics)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"[AI] Done in {enrichment_analytics['enrichment_time_s']} s  →  {output_file}")
    print(f"[AI] Material breakdown: {material_stats}")
    return enrichment_analytics


if __name__ == "__main__":
    enrich_surfaces("park_output.json", "park_output.json")