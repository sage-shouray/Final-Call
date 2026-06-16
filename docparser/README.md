# DocParser

> **Intelligent SAP Document Processing** — extract, validate, and post structured data from invoices, purchase orders, goods receipts, and more.

---

## Architecture

```
docparser/
├── apps/
│   ├── web/           React 18 + TypeScript + Vite + Tailwind  (port 3000)
│   └── api/           Python 3.11 + FastAPI + Motor            (port 8000)
├── packages/
│   └── shared-types/  Shared TypeScript domain types
└── docker/
    ├── docker-compose.yml      Production stack
    ├── docker-compose.dev.yml  Dev overrides (hot-reload + admin UIs)
    └── nginx/nginx.conf        Reverse proxy config
```

### Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, TanStack Query, Zustand |
| Backend | Python 3.11, FastAPI, Motor (async MongoDB), Celery + Redis |
| Database | MongoDB 7 |
| Cache / Queue | Redis 7 |
| AI extraction | Google Gemini 1.5 Pro |
| SAP integration | RFC / OData via aiohttp |
| Proxy | Nginx 1.25 |
| Container | Docker + Docker Compose |

---

## Prerequisites

| Tool | Minimum version |
|---|---|
| Docker + Docker Compose | 24.x / v2 |
| Node.js | 20 LTS |
| pnpm | 8.x (`npm i -g pnpm`) |
| Python | 3.11 |

---

## Quick Start (Docker — recommended)

```bash
# 1. Clone and enter repo
git clone <repo-url> docparser && cd docparser

# 2. Create your env file
cp .env.example .env
# Edit .env — at minimum set GEMINI_API_KEY, SAP_BASE_URL, JWT_SECRET

# 3. Start production stack
docker compose -f docker/docker-compose.yml up --build -d

# 4. Open the app
open http://localhost
```

To bring everything down:
```bash
docker compose -f docker/docker-compose.yml down
```

---

## Local Development (without Docker)

### Frontend

```bash
cd apps/web
pnpm install
pnpm dev
# → http://localhost:3000
```

### Backend

```bash
cd apps/api

# Create and activate virtualenv
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy env and configure
cp ../../.env.example ../../.env

# Start API server (requires MongoDB + Redis running)
uvicorn src.main:app --reload --port 8000
```

### Celery Worker (separate terminal)

```bash
cd apps/api
source .venv/bin/activate
celery -A src.workers.celery_app worker --loglevel=debug
```

---

## Development Stack with Docker

Includes Mongo Express (`:8081`) and Redis Commander (`:8082`):

```bash
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.dev.yml \
  up --build
```

---

## Environment Variables

Copy `.env.example` → `.env` and fill in all values.

| Variable | Description | Required |
|---|---|---|
| `MONGODB_URL` | MongoDB connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `JWT_SECRET` | Secret for signing JWTs (min 32 chars) | Yes |
| `GEMINI_API_KEY` | Google Gemini API key for document extraction | Yes |
| `SAP_BASE_URL` | Base URL of your SAP system | Yes |
| `SAP_CLIENT` | SAP client number | Yes |
| `SAP_USERNAME` | SAP RFC/OData username | Yes |
| `SAP_PASSWORD` | SAP RFC/OData password | Yes |
| `CORS_ORIGINS` | Comma-separated allowed origins | Yes |
| `SENTRY_DSN` | Sentry error tracking DSN | Recommended |
| `S3_BUCKET` | S3 bucket name for file storage | Yes |
| `AWS_ACCESS_KEY` | AWS / S3-compatible access key | Yes |
| `AWS_SECRET_KEY` | AWS / S3-compatible secret key | Yes |

---

## API Documentation

With `ENV=development`, interactive docs are available at:

- **Swagger UI** → `http://localhost:8000/api/docs`
- **ReDoc** → `http://localhost:8000/api/redoc`
- **OpenAPI JSON** → `http://localhost:8000/api/openapi.json`

---

## Health Checks

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness — reports service status |
| `GET /api/health/ready` | Readiness probe |

---

## Running Tests

### Frontend

```bash
cd apps/web
pnpm type-check
pnpm lint
```

### Backend

```bash
cd apps/api
pytest
# With coverage:
pytest --cov=src --cov-report=html
```

---

## Project Structure (API)

```
apps/api/src/
├── main.py          FastAPI app factory + lifespan
├── config.py        Pydantic-settings configuration
├── database.py      Motor async MongoDB client
├── routers/         API route handlers (one file per domain)
├── services/        Business logic layer
├── repositories/    Data access layer (MongoDB queries)
├── models/          MongoDB document models
├── schemas/         Pydantic request/response schemas
├── middleware/       Auth, logging, error-handling middleware
├── workers/         Celery task definitions
└── utils/           Shared helpers
```

---

## Code Quality

```bash
# Frontend
pnpm lint          # ESLint
pnpm format        # Prettier
pnpm type-check    # tsc --noEmit

# Backend
ruff check src/    # Linting
ruff format src/   # Formatting
mypy src/          # Type checking
```

---

## License

Private — All rights reserved.
