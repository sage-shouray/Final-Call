# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# python:3.11-slim omits curl deliberately — but docker-compose.yml's own
# healthcheck runs "curl -f http://localhost:8000/api/health/ready" *inside*
# this container to probe itself. Without the binary, that check fails
# immediately regardless of whether the app is actually fine, and the
# container gets marked unhealthy for a reason that has nothing to do with
# its own code.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- deps layer (cached separately) ----
FROM base AS deps
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---- runtime ----
FROM deps AS runtime
COPY src/ ./src/
# alembic.ini and the migrations themselves live one level up from src/ — both
# were missing from every image built before this, so `alembic upgrade head`
# had nothing to find script_location from. Nothing surfaced it earlier
# because this command had never actually been run inside a real container.
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
