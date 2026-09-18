import math
from typing import List, Dict, Any, Optional
from app.models import DirectiveInterpretation, BatteryConfig

VALID_DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}

def validate_and_guardrail_directives(
    raw_directives: List[Dict[str, Any]],
    operator_notes: List[str],
    battery: BatteryConfig
) -> List[DirectiveInterpretation]:
    """
    Applies deterministic guardrails (Section 08 of Problem Statement)
    to sanitize and strictly validate LLM interpretations.
    """
    guardrailed: List[DirectiveInterpretation] = []
    num_notes = len(operator_notes)
    
    # Map by note_index to handle potential out-of-order responses from LLM
    by_index: Dict[int, Dict[str, Any]] = {}
    for d in raw_directives:
        if isinstance(d, dict) and "note_index" in d:
            idx = int(d["note_index"])
            if 0 <= idx < num_notes:
                by_index[idx] = d

    for idx in range(num_notes):
        raw = by_index.get(idx)
        if not raw:
            # Fallback for missing note
            guardrailed.append(DirectiveInterpretation(
                note_index=idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="No actionable constraint identified."
            ))
            continue
            
        dtype = str(raw.get("directive_type", "no_op")).strip()
        if dtype not in VALID_DIRECTIVE_TYPES:
            dtype = "no_op"
            
        applies = bool(raw.get("applies", False))
        if dtype == "no_op":
            applies = False
        else:
            applies = True
            
        explanation = str(raw.get("explanation") or "Processed operator note.")
        adj = raw.get("structured_adjustment")
        
        if not applies or dtype == "no_op" or not isinstance(adj, dict):
            guardrailed.append(DirectiveInterpretation(
                note_index=idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation=explanation
            ))
            continue
            
        # Validate hours
        raw_hours = adj.get("hours", [])
        if not isinstance(raw_hours, list):
            raw_hours = []
        valid_hours = sorted(list(set(int(h) for h in raw_hours if isinstance(h, (int, float)) and 0 <= int(h) <= 23)))
        
        if not valid_hours:
            # If no valid hours extracted, treat as no_op
            guardrailed.append(DirectiveInterpretation(
                note_index=idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="No valid hours specified for directive."
            ))
            continue
            
        sanitized_adj: Dict[str, Any] = {"hours": valid_hours}
        
        if dtype == "solar_reduction":
            factor = float(adj.get("factor", 1.0))
            factor = max(0.0, min(1.0, factor))
            sanitized_adj["factor"] = factor
            
        elif dtype == "minimum_battery_reserve":
            min_energy = float(adj.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            min_energy = max(0.0, min(battery.capacity_kwh, min_energy))
            sanitized_adj["minimum_energy_kwh"] = min_energy
            
        elif dtype == "max_grid_window":
            max_grid = float(adj.get("max_grid_kwh", 0.0))
            max_grid = max(0.0, max_grid)
            sanitized_adj["max_grid_kwh"] = max_grid
            
        elif dtype in ("no_charge_window", "no_discharge_window"):
            pass  # Only hours needed
            
        guardrailed.append(DirectiveInterpretation(
            note_index=idx,
            applies=True,
            directive_type=dtype,
            structured_adjustment=sanitized_adj,
            explanation=explanation
        ))
        
    return guardrailed
