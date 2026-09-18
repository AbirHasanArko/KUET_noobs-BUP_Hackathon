import logging
from typing import List, Tuple
from app.models import OptimizeEnergyRequest, DirectiveInterpretation, HourlyPlan

logger = logging.getLogger(__name__)

def validate_final_schedule(
    request: OptimizeEnergyRequest,
    directives: List[DirectiveInterpretation],
    hourly_plan: List[HourlyPlan]
) -> Tuple[bool, List[str]]:
    """
    Final Validator (Step 5 in End-to-End Processing Flow):
    Independently replays the completed 24-hour schedule against
    all GridWise physical constraints and organizer ground-truth directives.
    """
    violations = []
    hours = request.hours
    battery = request.battery
    
    # 1. Check plan length and hour indexing
    if len(hourly_plan) != 24:
        violations.append(f"hourly_plan contains {len(hourly_plan)} hours instead of 24.")
        return False, violations
        
    # 2. Compute effective solar and active constraints per hour
    eff_solar = [h.solar_kwh for h in hours]
    min_reserve = [battery.minimum_energy_kwh for _ in range(24)]
    allow_charge = [True] * 24
    allow_discharge = [True] * 24
    max_grid = [float('inf')] * 24
    
    for d in directives:
        if not d.applies:
            continue
        dtype = d.directive_type
        adj = d.structured_adjustment or {}
        d_hours = adj.get("hours", [])
        
        if dtype == "solar_reduction":
            factor = adj.get("factor", 1.0)
            for h in d_hours:
                eff_solar[h] = hours[h].solar_kwh * factor
        elif dtype == "minimum_battery_reserve":
            m = adj.get("minimum_energy_kwh", battery.minimum_energy_kwh)
            for h in d_hours:
                min_reserve[h] = max(min_reserve[h], m)
        elif dtype == "no_charge_window":
            for h in d_hours:
                allow_charge[h] = False
        elif dtype == "no_discharge_window":
            for h in d_hours:
                allow_discharge[h] = False
        elif dtype == "max_grid_window":
            mg = adj.get("max_grid_kwh", float('inf'))
            for h in d_hours:
                max_grid[h] = min(max_grid[h], mg)

    # 3. Step-by-step physical replay
    prev_E = battery.initial_energy_kwh
    TOL = 0.05
    
    for h in range(24):
        p = hourly_plan[h]
        h_req = hours[h]
        
        # Action magnitude check
        c_h = p.battery_kwh if p.battery_action == "charge" else 0.0
        d_h = p.battery_kwh if p.battery_action == "discharge" else 0.0
        
        if p.battery_action == "idle" and abs(p.battery_kwh) > TOL:
            violations.append(f"Hour {h}: battery_kwh must be 0 when action is idle.")
            
        # Rate limits
        if c_h > battery.max_charge_kwh_per_hour + TOL:
            violations.append(f"Hour {h}: Charge {c_h} exceeds max charge limit {battery.max_charge_kwh_per_hour}.")
        if d_h > battery.max_discharge_kwh_per_hour + TOL:
            violations.append(f"Hour {h}: Discharge {d_h} exceeds max discharge limit {battery.max_discharge_kwh_per_hour}.")
            
        # Directive windows
        if not allow_charge[h] and c_h > TOL:
            violations.append(f"Hour {h}: Charging attempted during no_charge_window.")
        if not allow_discharge[h] and d_h > TOL:
            violations.append(f"Hour {h}: Discharging attempted during no_discharge_window.")
        if p.grid_kwh > max_grid[h] + TOL:
            violations.append(f"Hour {h}: Grid import {p.grid_kwh} exceeds max_grid limit {max_grid[h]}.")
            
        # Solar utilization
        if p.solar_used_kwh > eff_solar[h] + TOL:
            violations.append(f"Hour {h}: Solar used {p.solar_used_kwh} exceeds effective solar {eff_solar[h]}.")
            
        # Energy balance
        supplied = p.grid_kwh + p.solar_used_kwh + d_h
        demanded = h_req.demand_kwh + c_h
        if abs(supplied - demanded) > TOL:
            violations.append(f"Hour {h}: Energy balance mismatch (supplied {supplied:.2f} vs demanded {demanded:.2f}).")
            
        # Battery state evolution
        expected_E = prev_E + c_h - d_h
        if abs(p.battery_energy_after_kwh - expected_E) > TOL:
            violations.append(f"Hour {h}: Battery transition mismatch (reported {p.battery_energy_after_kwh:.2f} vs expected {expected_E:.2f}).")
            
        # Battery bounds
        if p.battery_energy_after_kwh < min_reserve[h] - TOL:
            violations.append(f"Hour {h}: Battery energy {p.battery_energy_after_kwh} below active reserve {min_reserve[h]}.")
        if p.battery_energy_after_kwh > battery.capacity_kwh + TOL:
            violations.append(f"Hour {h}: Battery energy {p.battery_energy_after_kwh} exceeds capacity {battery.capacity_kwh}.")
            
        prev_E = p.battery_energy_after_kwh

    # 4. End of day neutrality
    if abs(prev_E - battery.initial_energy_kwh) > TOL:
        violations.append(f"End-of-day battery neutrality violated: final {prev_E:.2f} != initial {battery.initial_energy_kwh:.2f}.")

    is_valid = len(violations) == 0
    if not is_valid:
        logger.warning(f"Final Validation failed for {request.scenario_id}: {violations}")
    return is_valid, violations
