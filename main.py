from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from models import OptimizeRequest, OptimizeResponse, HealthResponse
from llm_interpreter import interpret_notes
from optimizer import optimize_schedule

app = FastAPI(title="GridWise Optimization API")

@app.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "ok"}

@app.post("/optimize-energy", response_model=OptimizeResponse)
def optimize_energy(request: OptimizeRequest):
    try:
        # 1. Interpret notes using LLM
        interpretations = interpret_notes(request.operator_notes)
        
        # 2. Optimize schedule
        hourly_plan, total_grid, total_cost, peak_grid = optimize_schedule(
            request.hours,
            request.battery,
            interpretations
        )
        
        # 3. Formulate plan summary
        plan_summary = "Energy plan optimized successfully adhering to base rules and interpreted directives."
        
        # 4. Construct response
        response = OptimizeResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=interpretations,
            hourly_plan=hourly_plan,
            total_grid_kwh=total_grid,
            total_cost_bdt=total_cost,
            peak_grid_kwh=peak_grid,
            plan_summary=plan_summary
        )
        
        return response
        
    except Exception as e:
        # Safe failure
        print(f"Internal Error: {e}")
        raise HTTPException(status_code=500, detail="Controlled internal error processing the optimization request.")
