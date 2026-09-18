import os
import json
from typing import List
from google import genai
from google.genai import types
from pydantic import BaseModel
from models import DirectiveInterpretation

class InterpretationResponseWrapper(BaseModel):
    interpretations: List[DirectiveInterpretation]

def interpret_notes(notes: List[str]) -> List[DirectiveInterpretation]:
    """
    Calls the LLM to interpret a list of operator notes.
    """
    if not notes:
        return []
    
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    prompt = f"""You are an expert energy scheduling assistant. 
You must interpret the following operator notes and extract deterministic directives for a 24-hour energy scheduling model.
There are exactly {len(notes)} notes. You must return exactly {len(notes)} interpretations, preserving the note_index order (0 to {len(notes)-1}).

Available Directive Types:
- solar_reduction: Reduce usable solar during specific hours. Requires "hours" array and "factor" (number, 0 to 1, fraction remaining).
- minimum_battery_reserve: Keep battery energy at or above a level. Requires "hours" array and "minimum_energy_kwh".
- no_charge_window: Battery charging unavailable. Requires "hours" array.
- no_discharge_window: Battery discharging unavailable. Requires "hours" array.
- max_grid_window: Grid import limit. Requires "hours" array and "max_grid_kwh".
- no_op: Note does not affect schedule. "applies" must be false, "structured_adjustment" null.

Rules for structured_adjustment:
- "hours" is a list of unique integers from 0 to 23 in ascending order.
- Time windows are start-inclusive, end-exclusive. E.g., "1 PM to 3 PM" is hours [13, 14].

Rules for "applies":
- For no_op: applies = false and structured_adjustment = null.
- For all others: applies = true and structured_adjustment must match required shape.

Operator Notes:
"""
    for i, note in enumerate(notes):
        prompt += f"Note {i}: {note}\n"
        
    prompt += "\nOutput exactly the JSON object containing an 'interpretations' array satisfying the schema. Do not output anything else."
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=InterpretationResponseWrapper,
                temperature=0.0
            ),
        )
        
        result_json = json.loads(response.text)
        wrapper = InterpretationResponseWrapper(**result_json)
        
        # Fallback manual guardrails
        validated_interpretations = []
        for i, item in enumerate(wrapper.interpretations):
            # enforce index
            item.note_index = i
            
            if item.directive_type == "no_op":
                item.applies = False
                item.structured_adjustment = None
            else:
                item.applies = True
                if not item.structured_adjustment:
                    # Invalid, but safe fallback
                    item.applies = False
                    item.directive_type = "no_op"
                else:
                    item.structured_adjustment.hours = sorted(list(set(item.structured_adjustment.hours)))
                    
            validated_interpretations.append(item)
            
        return validated_interpretations

    except Exception as e:
        print(f"Error during LLM interpretation: {e}")
        # Safe fallback
        fallback = []
        for i, note in enumerate(notes):
            fallback.append(DirectiveInterpretation(
                note_index=i,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Fallback due to interpretation error."
            ))
        return fallback
