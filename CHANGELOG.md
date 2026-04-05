# Changelog

## [0.2.0] - 2026-04-01

### SDK

- Bumped to `verdictlens==0.2.0`
- Added Google Gemini auto-patcher (`wrap_google`) — covers Gemini 1.5 Pro/Flash and 2.0 Flash, including async client
- Cost tables updated: added xAI Grok-3/3-mini/2, Meta Llama 3.3 70B, Mistral models
- OpenTelemetry export (`VERDICTLENS_OTEL_ENDPOINT`) — optional OTLP gRPC span exporter for sending to Grafana, Jaeger, etc.
- `set_cost_estimator()` and `per_million_table()` are now public API — override pricing for private/fine-tuned models
- Fixed: `asyncio.gather` branches with nested `@trace` decorators occasionally lost parent context under high concurrency

### Backend

- `/version` endpoint — returns `api_version` and `sdk_version`
- Root `GET /` now serves a branded landing page instead of a 404
- CORS default changed from `*` to `http://localhost:3000,http://localhost:5173` — set `VERDICTLENS_CORS_ORIGINS` to override

### Frontend

- Settings page now fetches SDK version from `/version` instead of hardcoding it
- Added Vitest + React Testing Library (10 tests across EmptyState, MetricCard, StatusBadge)

### CI

- Added `frontend-checks` job to GitHub Actions — runs lint + type check + build + tests on every push

---

## [0.1.0] - 2026-03-25

Initial release. Rough around some edges but the core stuff works.

### What's in it

- **SDK** — `@trace` decorator, async non-blocking ingestion, disk queue fallback, <2ms p99
- **Auto-patchers** — OpenAI (+ Groq, xAI, any OpenAI-compatible), Anthropic
- **Framework integrations** — LangChain, CrewAI, AutoGen, LlamaIndex
- **Blame analysis** — 5-pass root cause engine, ORIGINATOR / PROPAGATOR / MANIFESTOR / CLEAN roles
- **Replay** — re-run any span with edited inputs, real LLM calls, side-by-side diff
- **Datasets** — create from traces or via SDK, export as JSONL
- **Evaluations** — exact_match, contains, llm_judge scorers; replay and live modes; comparison view
- **Prompt playground** — model selector, temperature/tokens, rate limiting, cost guard
- **Prompt hub** — versioning, publish/unpublish, promote older versions, usage stats
- **Alerts** — error rate, latency, cost threshold rules with webhook notifications
- **Multi-workspace** — scoped API keys, SHA-256 hashed, full data isolation
- **Live feed** — real-time WebSocket trace stream via Redis pub/sub
- **Docker Compose** — one command, five services, health checks on everything

[0.2.0]: https://github.com/verdictlens/verdictlens/releases/tag/v0.2.0
[0.1.0]: https://github.com/verdictlens/verdictlens/releases/tag/v0.1.0
