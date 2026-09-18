import pulp
from typing import List, Tuple
from models import HourEntry, BatteryLimits, DirectiveInterpretation, HourlyPlanEntry

def optimize_schedule(
    hours: List[HourEntry],
    battery: BatteryLimits,
    directives: List[DirectiveInterpretation]
) -> Tuple[List[HourlyPlanEntry], float, float, float]:
    
    # Sort hours to ensure sequential processing
    hours = sorted(hours, key=lambda x: x.hour)
    
    # 1. Apply directives to base limits
    effective_solar = [h.solar_kwh for h in hours]
    min_reserves = [battery.minimum_energy_kwh for _ in range(24)]
    max_charge_rates = [battery.max_charge_kwh_per_hour for _ in range(24)]
    max_discharge_rates = [battery.max_discharge_kwh_per_hour for _ in range(24)]
    max_grid = [None for _ in range(24)]
    
    for d in directives:
        if not d.applies or d.directive_type == "no_op" or not d.structured_adjustment:
            continue
            
        adj = d.structured_adjustment
        for h in adj.hours:
            if h < 0 or h > 23: continue
            
            if d.directive_type == "solar_reduction":
                factor = adj.factor if adj.factor is not None else 1.0
                effective_solar[h] = hours[h].solar_kwh * factor
            elif d.directive_type == "minimum_battery_reserve":
                if adj.minimum_energy_kwh is not None:
                    min_reserves[h] = max(min_reserves[h], adj.minimum_energy_kwh)
            elif d.directive_type == "no_charge_window":
                max_charge_rates[h] = 0.0
            elif d.directive_type == "no_discharge_window":
                max_discharge_rates[h] = 0.0
            elif d.directive_type == "max_grid_window":
                if adj.max_grid_kwh is not None:
                    if max_grid[h] is None:
                        max_grid[h] = adj.max_grid_kwh
                    else:
                        max_grid[h] = min(max_grid[h], adj.max_grid_kwh)
                        
    # 2. Build the LP model
    prob = pulp.LpProblem("GridWiseOptimization", pulp.LpMinimize)
    
    grid_vars = []
    solar_used_vars = []
    charge_vars = []
    discharge_vars = []
    battery_energy_vars = []
    
    for h in range(24):
        grid_vars.append(pulp.LpVariable(f"grid_{h}", lowBound=0))
        solar_used_vars.append(pulp.LpVariable(f"solar_used_{h}", lowBound=0, upBound=effective_solar[h]))
        charge_vars.append(pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=max_charge_rates[h]))
        discharge_vars.append(pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=max_discharge_rates[h]))
        
        battery_energy_vars.append(pulp.LpVariable(
            f"battery_energy_{h}", 
            lowBound=min_reserves[h], 
            upBound=battery.capacity_kwh
        ))
        
        if max_grid[h] is not None:
            prob += grid_vars[h] <= max_grid[h]
            
    # Objective: Minimize sum(grid_kwh * tariff)
    prob += pulp.lpSum([grid_vars[h] * hours[h].tariff_bdt_per_kwh for h in range(24)])
    
    # Constraints
    for h in range(24):
        # Energy balance
        prob += grid_vars[h] + solar_used_vars[h] + discharge_vars[h] == hours[h].demand_kwh + charge_vars[h]
        
        # Battery state update
        if h == 0:
            e_before = battery.initial_energy_kwh
        else:
            e_before = battery_energy_vars[h-1]
            
        prob += battery_energy_vars[h] == e_before + charge_vars[h] - discharge_vars[h]
        
    # End-of-day neutrality
    prob += battery_energy_vars[23] == battery.initial_energy_kwh
    
    # Solve
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    
    # 3. Post-processing
    hourly_plan = []
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0
    
    for h in range(24):
        g_val = pulp.value(grid_vars[h])
        s_val = pulp.value(solar_used_vars[h])
        c_val = pulp.value(charge_vars[h])
        d_val = pulp.value(discharge_vars[h])
        e_after = pulp.value(battery_energy_vars[h])
        
        # Cleanup small float issues
        if g_val is None: g_val = 0.0
        if s_val is None: s_val = 0.0
        if c_val is None: c_val = 0.0
        if d_val is None: d_val = 0.0
        if e_after is None: e_after = 0.0

        if g_val < 1e-7: g_val = 0.0
        if s_val < 1e-7: s_val = 0.0
        if c_val < 1e-7: c_val = 0.0
        if d_val < 1e-7: d_val = 0.0
        
        # Resolve simultaneous charge/discharge
        net_charge = c_val - d_val
        if net_charge > 1e-7:
            b_action = "charge"
            b_kwh = net_charge
        elif net_charge < -1e-7:
            b_action = "discharge"
            b_kwh = -net_charge
        else:
            b_action = "idle"
            b_kwh = 0.0
            
        # Optional check: clip to min reserve
        if e_after < min_reserves[h]: e_after = min_reserves[h]
            
        entry = HourlyPlanEntry(
            hour=h,
            grid_kwh=round(g_val, 4),
            solar_used_kwh=round(s_val, 4),
            battery_action=b_action,
            battery_kwh=round(b_kwh, 4),
            battery_energy_after_kwh=round(e_after, 4)
        )
        hourly_plan.append(entry)
        
        total_grid += g_val
        total_cost += g_val * hours[h].tariff_bdt_per_kwh
        peak_grid = max(peak_grid, g_val)
        
    return hourly_plan, round(total_grid, 4), round(total_cost, 4), round(peak_grid, 4)
