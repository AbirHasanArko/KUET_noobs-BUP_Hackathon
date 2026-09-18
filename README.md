# GridWise Energy Optimization Challenge

This is a complete solution for the BUP CSE Fest 2026 Hackathon: GridWise LLM-Assisted Energy Optimization Challenge.

## Architecture Overview
This solution is an HTTP API service that optimizes a 24-hour campus energy schedule based on operational notes and energy models.
- **Framework**: `FastAPI` + `uvicorn` for robust, high-performance HTTP request handling.
- **LLM Provider**: `Google Gemini 2.5 Pro` via `google-genai` SDK for accurate, structured reasoning of operator notes.
- **Guardrails**: Strict schema enforcement using `Pydantic` and deterministic rule checking.
- **Optimizer**: `PuLP` using the CBC solver to formulate and solve the linear programming problem to guarantee minimum grid cost while strictly adhering to constraints.

## Prerequisites
- Docker (for containerized deployment)
- Python 3.10+ (for local development)
- Google Gemini API Key

## Local Quickstart

### 1. Clone & Configure
```bash
git clone <your-repo-url>
cd BUP_CSE_FEST_2026_Participant_Docs

# Set up environment variables
cp .env.example .env
# Edit .env and set your GEMINI_API_KEY
```

### 2. Run with Docker
```bash
docker build -t gridwise-app .
docker run -p 8000:8000 --env-file .env gridwise-app
```

### 3. Run Locally (Without Docker)
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

uvicorn main:app --host 0.0.0.0 --port 8000
```

## Testing Endpoints

### 1. Health Check
```bash
curl http://localhost:8000/health
```
**Expected Response:** `{"status": "ok"}`

### 2. Optimization Request
Run a public sample case against the endpoint:
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json 
```
*(Note: You will need to extract one single `case.input` object into a `sample_request.json` and use `-d @sample_request.json` since the sample case JSON contains an array of cases).*

## Dependencies and Limitations
- Relies on Google Gemini API for note interpretation. If the API rate limits are hit or the endpoint goes down, interpretation may safely fallback to a `no_op` failure.
- The CBC solver is installed in the Docker container to ensure LP compatibility.
