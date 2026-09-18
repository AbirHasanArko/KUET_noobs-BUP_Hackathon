import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.models import (
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
    HealthResponse
)
from app.llm_parser import interpret_operator_notes
from app.optimizer import solve_energy_schedule

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("GridWiseAPI")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GridWise Energy Optimization API service started.")
    yield
    logger.info("GridWise Energy Optimization API service shut down.")

app = FastAPI(
    title="GridWise Smart Campus Energy Optimization Service",
    description="LLM-Assisted Operator Directive Interpretation & 24-Hour Energy Scheduling API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check():
    """Readiness and health check endpoint for judge harness."""
    return HealthResponse(status="ok")

@app.post("/optimize-energy", response_model=OptimizeEnergyResponse, status_code=status.HTTP_200_OK)
async def optimize_energy(request: OptimizeEnergyRequest):
    """
    Main endpoint:
    1. Interprets 1-3 operator notes via LLM with deterministic guardrails.
    2. Formulates and solves linear programming optimization for 24-hour horizon.
    3. Returns machine-checkable directive interpretations and hourly energy plan.
    """
    try:
        # Step 1: Interpret operator notes
        directives = interpret_operator_notes(request.operator_notes, request.battery)
        
        # Step 2: Optimize energy schedule
        response = solve_energy_schedule(request, directives)
        
        return response
    except Exception as e:
        logger.error(f"Error processing scenario {request.scenario_id}: {e}", exc_info=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to optimize energy schedule for the scenario."
        )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=False)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."}
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
