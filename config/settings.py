import json
from pathlib import Path

# === API-Konfiguration ===
API_KEY = "test_api_key"

# === System-Prompt für LLM ===
SYSTEM_PROMPT = """
You are a precise assistant that converts natural-language process descriptions into valid WoPeD-compatible PNML Petri nets.

Strictly follow these rules:
- Return only a single valid <pnml>...</pnml> block – no code blocks, no explanations.
- All IDs (id="...") must be unique.
- Close every tag properly. Do not include malformed or duplicate elements.
- Use <toolspecific tool="WoPeD" version="3.9.2"> for WoPeD compatibility.
- Avoid any tag fragments or misplaced content.
- Transitions must be connected via valid arcs to places, and vice versa.
- Include <initialMarking> only on one place, typically the start.
- Ensure XML structure is valid and parsable.
"""

# === Few-Shot Templates laden ===
TEMPLATE_PATH = Path(__file__).parent / "few_shot_templates.json"

def load_few_shot_templates():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return json.load(f)

FEW_SHOT_TEMPLATES = load_few_shot_templates()
