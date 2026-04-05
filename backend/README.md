# verdictlens-backend

FastAPI backend for **VerdictLens** — trace ingestion, query, real-time streaming, and metrics.

## Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Requires ClickHouse on `localhost:8123` and (optionally) Redis on `localhost:6379`.
