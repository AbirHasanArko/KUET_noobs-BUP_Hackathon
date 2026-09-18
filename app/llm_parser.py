import os
import json
import re
import logging
from typing import List, Dict, Any, Optional
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from cachetools import cached, TTLCache
import hashlib
from app.models import BatteryConfig, DirectiveInterpretation
from app.guardrails import validate_and_guardrail_directives

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert energy scheduling AI assistant for the BUP Smart Campus Energy Challenge.
Your task is to analyze 1 to 3 natural-language operator notes and interpret each note into a structured directive.

Allowed Directive Types:
1. "solar_reduction": Usable solar drops or is reduced during specific hours.
   structured_adjustment: {"hours": [int, ...], "factor": float}
   NOTE: "factor" is the usable fraction remaining. An 80% reduction means factor = 0.2. "drop to 25%" means factor = 0.25. "half" means factor = 0.5. "one-fifth" means factor = 0.2.
2. "minimum_battery_reserve": Battery energy must stay at or above a required amount during specific hours.
   structured_adjustment: {"hours": [int, ...], "minimum_energy_kwh": float}
   NOTE: If expressed as a percentage of battery capacity (e.g. 50% of capacity), compute the numeric kWh value.
3. "no_charge_window": Battery charging is disabled/unavailable/isolated during specific hours.
   structured_adjustment: {"hours": [int, ...]}
4. "no_discharge_window": Battery discharging is disabled/unavailable during specific hours (e.g., protection test, relay test).
   structured_adjustment: {"hours": [int, ...]}
5. "max_grid_window": Grid import is capped at a maximum amount during specific hours (e.g., feeder limit, transformer limit, substation constraint).
   structured_adjustment: {"hours": [int, ...], "max_grid_kwh": float}
6. "no_op": The note is an irrelevant distractor (e.g., menu change, library hours, club notices, sports registration, room bookings) and does not affect the 24-hour energy schedule.
   applies: false, directive_type: "no_op", structured_adjustment: null.

Time Window Rules:
- Whole-hour intervals only. Start hour is included, end hour is excluded.
- Example: "1 PM to 3 PM" or "13:00 to 15:00" -> hours [13, 14].
- Example: "10 AM until noon" -> hours [10, 11].
- Example: "from 2 AM until 5 AM" -> hours [2, 3, 4].
- Example: "from 6 PM until 10 PM" -> hours [18, 19, 20, 21].
- Hours in structured_adjustment MUST be unique integers in ascending order.

Output Format:
Return ONLY a valid JSON object with the key "directives" containing an array of interpretation objects in note_index order:
{
  "directives": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
      "explanation": "Short explanation of the interpretation."
    }
  ]
}

Examples:
Input:
["The PV output will drop to 20% between 13:00 and 15:00", "The cafeteria menu changes tomorrow."]
Output:
{
  "directives": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
      "explanation": "Solar is reduced to 20% during 13:00-15:00."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "Cafeteria menu is irrelevant."
    }
  ]
}
"""

def parse_time_window(text: str) -> List[int]:
    text_lower = text.lower()
    text_lower = re.sub(r'\bnoon\b', '12 pm', text_lower)
    text_lower = re.sub(r'\bmidnight\b', '12 am', text_lower)
    text_lower = re.sub(r'\bone\b', '1', text_lower)
    text_lower = re.sub(r'\btwo\b', '2', text_lower)
    text_lower = re.sub(r'\bthree\b', '3', text_lower)
    text_lower = re.sub(r'\bfour\b', '4', text_lower)
    text_lower = re.sub(r'\bfive\b', '5', text_lower)
    text_lower = re.sub(r'\bsix\b', '6', text_lower)
    text_lower = re.sub(r'\bseven\b', '7', text_lower)
    text_lower = re.sub(r'\beight\b', '8', text_lower)
    text_lower = re.sub(r'\bnine\b', '9', text_lower)
    text_lower = re.sub(r'\bten\b', '10', text_lower)
    text_lower = re.sub(r'\beleven\b', '11', text_lower)
    text_lower = re.sub(r'\btwelve\b', '12', text_lower)
    
    # 24h format: "13:00 and 15:00", "13:00 to 15:00", "between 13 and 15"
    m = re.search(r'(\d{1,2}):?00?\s*(?:and|to|until|-)\s*(\d{1,2}):?00?', text_lower)
    if m:
        h1, h2 = int(m.group(1)), int(m.group(2))
        if 0 <= h1 < 24 and 0 < h2 <= 24 and h1 < h2:
            return list(range(h1, h2))

    # "1-3 PM", "1 - 3 PM", "1 to 3 PM"
    m = re.search(r'(\d{1,2})\s*(?:-|to|until|and)\s*(\d{1,2})\s*(am|pm)', text_lower)
    if m:
        h1, h2, period = int(m.group(1)), int(m.group(2)), m.group(3)
        if period == 'pm':
            if h1 < 12: h1 += 12
            if h2 < 12: h2 += 12
        elif period == 'am':
            if h1 == 12: h1 = 0
            if h2 == 12: h2 = 0
        if h1 < h2:
            return list(range(h1, h2))
            
    # "from 1 PM to 3 PM", "between 10 AM and 1 PM", "from 11 AM until 1 PM"
    m = re.search(r'(\d{1,2})\s*(am|pm)?\s*(?:to|until|and|-)\s*(\d{1,2})\s*(am|pm)', text_lower)
    if m:
        h1_raw, p1, h2_raw, p2 = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        if not p1:
            p1 = p2
        h1 = h1_raw
        h2 = h2_raw
        if p1 == 'pm' and h1 < 12: h1 += 12
        elif p1 == 'am' and h1 == 12: h1 = 0
        if p2 == 'pm' and h2 < 12: h2 += 12
        elif p2 == 'am' and h2 == 12: h2 = 0
        if h1 < h2:
            return list(range(h1, h2))
            
    return []

def fallback_heuristic_parse(note: str, note_idx: int, capacity_kwh: float) -> Dict[str, Any]:
    text = note.strip()
    text_lower = text.lower()
    
    distractor_keywords = [
        'cafeteria', 'book-return', 'library', 'club notices', 'seminar room',
        'student affairs', 'menu changes', 'sports office', 'registration deadline',
        'next week', 'next month', 'parking', 'bus schedule'
    ]
    if any(k in text_lower for k in distractor_keywords):
        return {
            "note_index": note_idx,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "This note does not affect today's 24-hour energy schedule."
        }
        
    hours = parse_time_window(text)
    if not hours:
        return {
            "note_index": note_idx,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "No actionable time window found."
        }
        
    # Solar reduction
    if any(k in text_lower for k in ['solar', 'pv', 'panel', 'cloud', 'sun', 'rooftop']):
        factor = 0.5
        m_pct = re.search(r'(\d+(?:\.\d+)?)%', text_lower)
        if any(k in text_lower for k in ['reduction', 'reduced by', 'drop by', 'cut by', 'decrease by']):
            if m_pct:
                reduction = float(m_pct.group(1)) / 100.0
                factor = round(1.0 - reduction, 4)
        elif m_pct:
            factor = float(m_pct.group(1)) / 100.0
        elif 'half' in text_lower or 'one-half' in text_lower:
            factor = 0.5
        elif 'one-fifth' in text_lower:
            factor = 0.2
        elif 'quarter' in text_lower:
            factor = 0.25

        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": hours, "factor": factor},
            "explanation": f"Solar output adjusted by factor {factor} during specified hours."
        }
        
    # Charge outage
    if any(k in text_lower for k in ['charger', 'charging', 'do not charge', 'charging circuit', 'cannot charge', 'isolate']) and not any(k in text_lower for k in ['not discharge', 'discharging', 'discharge']):
        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": "Battery charging is unavailable during the window."
        }
            
    # Discharge outage
    if any(k in text_lower for k in ['not discharge', 'discharging', 'discharge', 'protection test', 'relay testing']) and not any(k in text_lower for k in ['not charge', 'cannot charge']):
        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": "Battery discharging is unavailable during the window."
        }
            
    # Minimum battery reserve
    if any(k in text_lower for k in ['reserve', 'emergency', 'stored in the battery', 'remain in the battery', 'data center']) and any(k in text_lower for k in ['battery', 'capacity', 'reserve', 'stored', 'remain', 'kwh']):
        m_pct = re.search(r'(\d+)%', text_lower)
        if m_pct:
            pct = float(m_pct.group(1)) / 100.0
            min_energy = capacity_kwh * pct
        else:
            m_val = re.search(r'(\d+(?:\.\d+)?)\s*kwh', text_lower)
            min_energy = float(m_val.group(1)) if m_val else 0.0
        if min_energy == int(min_energy):
            min_energy = int(min_energy)
        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": hours, "minimum_energy_kwh": min_energy},
            "explanation": f"Battery reserve of {min_energy} kWh is required during the window."
        }

    # Grid cap
    if any(k in text_lower for k in ['grid import', 'grid intake', 'feeder', 'transformer', 'substation', 'grid', 'intake', 'import']):
        m = re.search(r'(\d+(?:\.\d+)?)\s*kwh', text_lower)
        max_grid = float(m.group(1)) if m else 0.0
        if max_grid == int(max_grid):
            max_grid = int(max_grid)
        return {
            "note_index": note_idx,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": hours, "max_grid_kwh": max_grid},
            "explanation": f"Grid import is capped at {max_grid} kWh during the window."
        }
        
    return {
        "note_index": note_idx,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "This note does not affect today's 24-hour energy schedule."
    }

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
def call_gemini_api(notes: List[str], capacity_kwh: float, api_key: str, model_name: str = "gemini-1.5-flash") -> Optional[List[Dict[str, Any]]]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    prompt_text = f"""Battery Capacity: {capacity_kwh} kWh
Operator Notes:
{json.dumps(notes, indent=2)}

Please interpret each note according to the instructions and return valid JSON."""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": SYSTEM_PROMPT + "\n\n" + prompt_text}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            content_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            parsed = json.loads(content_text)
            if isinstance(parsed, dict) and "directives" in parsed:
                return parsed["directives"]
            elif isinstance(parsed, list):
                return parsed
    return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
def call_openai_compatible_api(notes: List[str], capacity_kwh: float, api_key: str, base_url: str, model_name: str) -> Optional[List[Dict[str, Any]]]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    prompt_text = f"""Battery Capacity: {capacity_kwh} kWh
Operator Notes:
{json.dumps(notes, indent=2)}

Please interpret each note according to the instructions and return valid JSON."""

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            content_text = choices[0].get("message", {}).get("content", "")
            parsed = json.loads(content_text)
            if isinstance(parsed, dict) and "directives" in parsed:
                return parsed["directives"]
            elif isinstance(parsed, list):
                return parsed
    return None

_llm_cache = TTLCache(maxsize=100, ttl=3600)

def hash_notes(operator_notes: List[str], battery: BatteryConfig) -> str:
    return hashlib.md5(json.dumps(operator_notes).encode('utf-8')).hexdigest()

@cached(cache=_llm_cache, key=hash_notes)
def interpret_operator_notes(
    operator_notes: List[str],
    battery: BatteryConfig
) -> List[DirectiveInterpretation]:
    """
    Main interpretation pipeline:
    1. Try configured LLM (Gemini / OpenAI / Groq / custom).
    2. Fallback to heuristic parser if API call fails or keys are missing.
    3. Run deterministic guardrails to guarantee strict schema compliance.
    """
    raw_directives: Optional[List[Dict[str, Any]]] = None
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    custom_base_url = os.getenv("OPENAI_BASE_URL")
    
    # 1. Try Gemini
    if gemini_key:
        try:
            model = os.getenv("LLM_MODEL", "gemini-3.6-flash")
            raw_directives = call_gemini_api(operator_notes, battery.capacity_kwh, gemini_key, model)
        except Exception as e:
            logger.warning(f"Gemini API call failed: {e}")

    # 2. Try OpenAI / Groq / custom if Gemini didn't run/succeed
    if not raw_directives and openai_key:
        try:
            model = os.getenv("LLM_MODEL", "gpt-4o-mini")
            base_url = custom_base_url or "https://api.openai.com/v1"
            raw_directives = call_openai_compatible_api(operator_notes, battery.capacity_kwh, openai_key, base_url, model)
        except Exception as e:
            logger.warning(f"OpenAI API call failed: {e}")

    if not raw_directives and groq_key:
        try:
            model = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
            base_url = "https://api.groq.com/openai/v1"
            raw_directives = call_openai_compatible_api(operator_notes, battery.capacity_kwh, groq_key, base_url, model)
        except Exception as e:
            logger.warning(f"Groq API call failed: {e}")

    # 3. Deterministic Heuristic Fallback
    if not raw_directives:
        raw_directives = [
            fallback_heuristic_parse(note, idx, battery.capacity_kwh)
            for idx, note in enumerate(operator_notes)
        ]

    # 4. Strict Deterministic Guardrails
    guardrailed = validate_and_guardrail_directives(raw_directives, operator_notes, battery)
    return guardrailed
