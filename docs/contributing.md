# Contributing to VerdictLens

We welcome contributions — especially new auto-patchers and framework integrations. This guide covers the project structure, how to add integrations, and how to submit changes.

---

## Project Structure

```
verdictlens/
├── sdk/                    # Python SDK (pip installable)
│   ├── verdictlens/          # Package source
│   │   ├── __init__.py     # Public API exports
│   │   ├── config.py       # Configuration (env vars, settings)
│   │   ├── client.py       # HTTP transport + background workers
│   │   ├── trace.py        # @trace decorator, contextvars span stack
│   │   ├── patchers.py     # wrap_openai(), wrap_anthropic(), wrap_google() auto-patchers
│   │   ├── types.py        # Pydantic models (TraceEvent, SpanRecord)
│   │   ├── schema.py       # Canonical schema contract (single source of truth)
│   │   ├── serializers.py  # Safe JSON serialization
│   │   ├── pricing.py      # Cost estimation hooks
│   │   └── queue.py        # On-disk offline queue
│   └── tests/
├── backend/                # FastAPI server
│   ├── app/
│   │   ├── main.py         # App factory + lifespan
│   │   ├── routes.py       # API endpoints
│   │   ├── clickhouse.py   # ClickHouse queries + schema (parent_span_id indexed)
│   │   ├── models.py       # Request/response models
│   │   ├── blame.py        # Tree-aware blame engine
│   │   ├── replay.py       # Replay with parent context reconstruction
│   │   ├── live.py         # WebSocket broadcast
│   │   └── settings.py     # Env-driven config
│   └── tests/
├── frontend/               # React + Tailwind dashboard
│   └── src/
│       ├── lib/            # API client, WebSocket hook, utils
│       ├── components/     # SpanTree (recursive), PeekPanel, JsonViewer
│       └── pages/          # Route pages (Dashboard, Traces, Blame, etc.)
├── examples/
│   └── demo.py             # Hierarchical trace demo (18 traces, 4-level trees)
├── deploy/                 # ClickHouse init scripts
├── docker-compose.yml
└── docs/
```

---

## Development Setup

### SDK

```bash
cd sdk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

Backend tests use an in-memory fake store — no ClickHouse or Redis required.

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
npm run build        # Production build
npx tsc --noEmit     # Type check
```

### Full Stack (Docker)

```bash
cp .env.example .env
docker compose up -d --build
python examples/demo.py   # Populate with hierarchical traces
```

---

## Adding a New Auto-Patcher

Auto-patchers are the highest-leverage contribution. They let users trace LLM calls with zero code changes.

### How auto-patchers work

1. `wrap_openai(client)` monkey-patches `client.chat.completions.create`
2. The patched method checks for an active `@trace` context via `contextvars`
3. If active, it wraps the call to record timing, tokens, cost, and I/O as a child span
4. If no active context, the original method runs unmodified

### Adding a new patcher (e.g., `wrap_cohere`)

In `sdk/verdictlens/patchers.py`, add:

```python
def wrap_cohere(client: T) -> T:
    """Patch a Cohere client so chat() auto-traces."""
    chat = getattr(client, "chat", None)
    if chat is None or getattr(chat, "_verdictlens_patched", False):
        return client

    original = chat
    
    @functools.wraps(original)
    def patched(*args, **kwargs):
        if _active_span.get() is None:
            return original(*args, **kwargs)
        return _trace_cohere_sync(original, args, kwargs)

    client.chat = patched
    client.chat._verdictlens_patched = True
    return client
```

Key patterns:
- Use `_active_span.get()` to check for active trace context
- Use `record_child_span()` to add the span to the tree
- Make it idempotent with `_verdictlens_patched` flag
- Handle both sync and async variants
- Never crash — catch all exceptions from the tracing layer

### Export it

In `sdk/verdictlens/__init__.py`, add the import and `__all__` entry.

### Test it

```python
def test_wrap_cohere_creates_child_span(captured_traces):
    # Setup mock client
    # Call wrapped method inside @trace
    # Assert child span exists with correct parent_span_id
```

---

## Modifying the Blame Engine

The blame engine in `backend/app/blame.py` is tree-aware:

1. **Builds a `SpanNode` tree** from `parent_span_id` relationships
2. **Computes per-node scores** using weighted formula (input anomaly, output deviation, confidence, error propagation, tree depth)
3. **Walks the tree DFS** for cascade narrative
4. **Follows tree paths** for the full chain

If you modify the scoring formula, update the weights at the top of the file and test with the demo traces.

---

## Code Standards

- **Type hints** on every function signature
- **Docstrings** on every public function (`:param:` / `:returns:` format)
- **Error handling** — never crash silently; log warnings, fall back gracefully
- **Safe serialization** — always use `safe_serialize()` for user-controlled data
- **Bounded payloads** — strings truncated at 16 KB, collections at 256 items, depth at 8

---

## Pull Request Checklist

- [ ] Code has type hints and docstrings
- [ ] Tests pass (`pytest` in `sdk/` and `backend/`)
- [ ] No new dependencies without justification
- [ ] Frontend builds cleanly (`npm run build` + `npx tsc --noEmit`)
- [ ] Existing tests still pass
