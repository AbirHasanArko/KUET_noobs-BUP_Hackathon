from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class HourEntry(BaseModel):
    hour: int = Field(ge=0, le=23)
    demand_kwh: float
    solar_kwh: float
    tariff_bdt_per_kwh: float

class BatteryLimits(BaseModel):
    capacity_kwh: float
    initial_energy_kwh: float
    minimum_energy_kwh: float
    max_charge_kwh_per_hour: float
    max_discharge_kwh_per_hour: float

class OptimizeRequest(BaseModel):
    scenario_id: str
    operator_notes: List[str] = Field(min_length=1, max_length=3)
    hours: List[HourEntry] = Field(min_length=24, max_length=24)
    battery: BatteryLimits

class StructuredAdjustment(BaseModel):
    hours: List[int]
    factor: Optional[float] = None
    minimum_energy_kwh: Optional[float] = None
    max_grid_kwh: Optional[float] = None

class DirectiveInterpretation(BaseModel):
    note_index: int
    applies: bool
    directive_type: Literal[
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op"
    ]
    structured_adjustment: Optional[StructuredAdjustment] = None
    explanation: str

class HourlyPlanEntry(BaseModel):
    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float
    battery_energy_after_kwh: float

class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str

class HealthResponse(BaseModel):
    status: str
