# Self-Hosting Guide

**Needs:** Docker 20.10+, Docker Compose v2, 2GB RAM, 10GB disk.

---

## Quick Start

```bash
git clone https://github.com/verdictlens/verdictlens.git
cd verdictlens
cp .env.example .env
docker compose up -d
```

Takes about 30 seconds for everything to become healthy (ClickHouse is the slow one):

```bash
docker compose ps
```

| Service | URL | Purpose |
|---|---|---|
| Dashboard | http://localhost:3000 | Web UI |
| API | http://localhost:8000 | Trace ingestion + query |
| API Docs | http://localhost:8000/docs | Interactive Swagger UI |
| ClickHouse | http://localhost:8123 | Direct DB access (advanced) |

---

## Configuration

Everything is env vars in `.env`. Copy `.env.example` and change what you need — defaults work fine for local use.

### API Server

| Variable | Default | Description |
|---|---|---|
| `VERDICTLENS_HOST` | `0.0.0.0` | Bind address |
| `VERDICTLENS_PORT` | `8000` | API port |
| `VERDICTLENS_DEBUG` | `false` | Enable debug logging |
| `VERDICTLENS_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `VERDICTLENS_API_KEY` | *(empty)* | Required Bearer token for `POST /traces` |

### ClickHouse

| Variable | Default | Description |
|---|---|---|
| `VERDICTLENS_CH_HOST` | `clickhouse` | ClickHouse hostname |
| `VERDICTLENS_CH_PORT` | `8123` | ClickHouse HTTP port |
| `VERDICTLENS_CH_USER` | `default` | ClickHouse username |
| `VERDICTLENS_CH_PASSWORD` | *(empty)* | ClickHouse password |
| `VERDICTLENS_CH_DATABASE` | `verdictlens` | Database name |

### Redis

| Variable | Default | Description |
|---|---|---|
| `VERDICTLENS_REDIS_URL` | `redis://redis:6379/0` | Redis connection string |

### Port Mapping

| Variable | Default | Description |
|---|---|---|
| `API_PORT` | `8000` | Host port for the API |
| `UI_PORT` | `3000` | Host port for the dashboard |
| `CLICKHOUSE_HTTP_PORT` | `8123` | Host port for ClickHouse HTTP |
| `REDIS_PORT` | `6379` | Host port for Redis |

---

## Production Deployment

### Enable authentication

By default auth is off — fine for local use, not for anything public. Set an API key:

```bash
# .env
VERDICTLENS_API_KEY=your-secret-key-here
```

Then configure the SDK:

```python
from verdictlens import configure
configure(base_url="https://verdictlens.yourcompany.com", api_key="your-secret-key-here")
```

### Put behind a reverse proxy

For HTTPS, put nginx/Caddy/Traefik in front of the `verdictlens-ui` container. The nginx inside the container already proxies `/api/` and `/ws/` to the backend.

Example with Caddy:

```
verdictlens.yourcompany.com {
    reverse_proxy localhost:3000
}
```

### Restrict CORS

```bash
VERDICTLENS_CORS_ORIGINS=https://verdictlens.yourcompany.com
```

### Scale the API

For higher ingest throughput, increase uvicorn workers in `backend/Dockerfile`:

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

Or run multiple `verdictlens-api` replicas behind a load balancer. Redis Pub/Sub ensures all replicas share the same live WebSocket feed.

### ClickHouse tuning

For high-volume deployments (>100k traces/day):

- Increase ClickHouse memory: set `CLICKHOUSE_MAX_MEMORY_USAGE` 
- Add TTL policies to auto-expire old data
- Consider ClickHouse Cloud for managed scaling

---

## Data Management

### Backup

ClickHouse data lives in the `clickhouse_data` Docker volume:

```bash
docker compose exec clickhouse clickhouse-client \
  --query "SELECT * FROM verdictlens.traces FORMAT JSONEachRow" > traces_backup.jsonl
```

### Retention

Add TTL to auto-delete old traces:

```sql
ALTER TABLE verdictlens.traces MODIFY TTL start_time + INTERVAL 90 DAY;
ALTER TABLE verdictlens.spans MODIFY TTL start_time + INTERVAL 90 DAY;
```

### Reset

```bash
docker compose down -v   # Removes all volumes (data loss!)
docker compose up -d     # Fresh start
```

### Populate with demo data

After a fresh start, run the demo to generate hierarchical traces:

```bash
pip install -e ./sdk
python examples/demo.py
```

This sends 18 traces with nested span trees (up to 4 levels deep), including parallel async branches and intentional failures for blame analysis.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Dashboard shows "Loading…" | API not reachable | Check `docker compose logs verdictlens-api` |
| Traces not appearing | SDK pointed to wrong URL | Verify `configure(base_url=...)` matches your API |
| ClickHouse OOM | Large trace payloads | Increase Docker memory limit, add TTL |
| WebSocket disconnects | Redis down | Check `docker compose logs redis` |
| 401 on POST /traces | API key mismatch | Ensure SDK `api_key` matches `VERDICTLENS_API_KEY` |
