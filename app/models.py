from typing import List, Optional, Any, Dict, Literal
from pydantic import BaseModel, Field, ConfigDict

class HourlyDemand(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day 0-23")
    demand_kwh: float = Field(..., ge=0, description="Campus demand in kWh")
    solar_kwh: float = Field(..., ge=0, description="Available solar generation in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid tariff in BDT/kWh")

class BatteryConfig(BaseModel):
    capacity_kwh: float = Field(..., gt=0, description="Maximum battery capacity in kWh")
    initial_energy_kwh: float = Field(..., ge=0, description="Starting battery energy in kWh")
    minimum_energy_kwh: float = Field(..., ge=0, description="Base minimum energy reserve in kWh")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Max charging rate in kWh/h")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Max discharging rate in kWh/h")

class OptimizeEnergyRequest(BaseModel):
    scenario_id: str = Field(..., description="Unique scenario identifier")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1-3 natural-language notes")
    hours: List[HourlyDemand] = Field(..., min_length=24, max_length=24, description="Exactly 24 hourly entries")
    battery: BatteryConfig

class DirectiveInterpretation(BaseModel):
    note_index: int = Field(..., ge=0, description="Index of operator note")
    applies: bool = Field(..., description="Whether this note applies to energy scheduling")
    directive_type: Literal[
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op"
    ] = Field(..., description="Identified directive type")
    structured_adjustment: Optional[Dict[str, Any]] = Field(None, description="Adjustment object or null for no_op")
    explanation: str = Field(..., description="Human-readable explanation of interpretation")

class HourlyPlan(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0, description="Grid electricity imported in kWh")
    solar_used_kwh: float = Field(..., ge=0, description="Solar electricity used in kWh")
    battery_action: Literal["charge", "discharge", "idle"] = Field(..., description="Battery action in this hour")
    battery_kwh: float = Field(..., ge=0, description="Magnitude of battery charge/discharge")
    battery_energy_after_kwh: float = Field(..., ge=0, description="Battery energy state after this hour")

class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlan]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str

class HealthResponse(BaseModel):
    status: str = "ok"
