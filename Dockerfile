FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

WORKDIR /app

# Install system dependencies for optimization solver (CBC solver is built into pulp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    coinor-cbc \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt httpx

# Copy application source code
COPY app/ ./app/
EXPOSE 8000

# Run uvicorn server binding to 0.0.0.0
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
