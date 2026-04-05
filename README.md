# VerdictLens

Your agent failed. You don't know which one.

That's the problem I kept running into - multi-agent pipelines where something breaks in step 2, causes a silent bad state, and the whole thing blows up in step 7. Every existing tool just shows you a flat list of spans. None of them tell you *who started it*.

VerdictLens does. It traverses the span tree, classifies every agent as ORIGINATOR / PROPAGATOR / MANIFESTOR / CLEAN, and gives you a single sentence explaining what broke and why.

```json
{
  "originator": {
    "span_name": "planning_agent",
    "blame_score": 0.87,
    "reason": "Produced null output. Caused downstream failure in summary_agent."
  },
  "failure_point": {
    "span_name": "summary_agent",
    "role": "MANIFESTOR",
    "caused_by": "planning_agent"
  },
  "propagation_chain": ["planning_agent → summary_agent"],
  "confidence": "high",
  "human_summary": "planning_agent introduced a null output (context window exceeded in openai.create). This null propagated to summary_agent which failed as a result."
}
```

Self-hosted. Open source. One `docker compose up` and you're running.

---

## Why I built this

LangSmith is closed source and charges per seat. Langfuse is good but framework-heavy. Neither one does blame analysis — they show you what happened, not *why* it happened or *which agent* caused it.

I wanted something I could run on my own infra, that works with any Python LLM framework, and that actually points a finger when something goes wrong.

That's VerdictLens.

---

## What it does

- **Blame analysis** — traverses the span tree to find the root cause agent. The only tool that does this.
- **Replay debugging** — re-run any span with edited inputs. Makes a real LLM call, shows side-by-side diff.
- **Dataset builder** — save any trace or span as a labeled example with one click
- **Evaluation engine** — score examples with exact_match, contains, or LLM judge. Compare pipeline versions.
- **Prompt playground** — edit, tune, iterate. Safety guardrails so you don't accidentally send a 50k token prompt.
- **Prompt hub** — version and share prompts across your team
- **Multi-workspace** — full isolation with scoped API keys
- **Under 2ms overhead** — async, non-blocking, disk-backed queue if the server's unreachable

---

## Quickstart

```bash
git clone https://github.com/verdictlens/verdictlens.git
cd verdictlens
docker compose up -d --build
pip install -e ./sdk
```

```python
from openai import OpenAI
from verdictlens import configure, trace, wrap_openai

configure(base_url="http://localhost:8000")
client = wrap_openai(OpenAI())

@trace(name="my_agent", span_type="agent")
def my_agent(query: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": query}]
    )
    return response.choices[0].message.content

my_agent("What is quantum computing?")
```

Open **http://localhost:3000**. Your trace is there.

```
my_agent (agent, 2100ms)
└── openai.chat.completions.create(gpt-4o-mini) (llm, 2050ms)
    tokens: 150 prompt, 280 completion
    cost: $0.0002
```

---

## Auto-instrumentation

Wrap your LLM client once. Every call inside a `@trace` context automatically becomes a child span — model, tokens, cost, latency, all captured.

### OpenAI / Groq / xAI

```python
from openai import OpenAI
from verdictlens import configure, trace, wrap_openai

configure(base_url="http://localhost:8000")
client = wrap_openai(OpenAI())

@trace(name="research_pipeline", span_type="chain")
def research_pipeline(topic: str) -> dict:
    findings = rag_agent(topic)
    review = review_agent(findings)
    return {"findings": findings, "review": review}

@trace(name="rag_agent", span_type="agent")
def rag_agent(topic: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Research: {topic}"}]
    )
    return response.choices[0].message.content

@trace(name="review_agent", span_type="agent")
def review_agent(findings: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Review: {findings}"}]
    )
    return response.choices[0].message.content
```

Produces a 3-level tree:

```
research_pipeline (chain)
├── rag_agent (agent)
│   └── openai.chat.completions.create(gpt-4o) (llm)
└── review_agent (agent)
    └── openai.chat.completions.create(gpt-4o-mini) (llm)
```

### Anthropic

```python
from anthropic import Anthropic
from verdictlens import configure, trace, wrap_anthropic

configure(base_url="http://localhost:8000")
client = wrap_anthropic(Anthropic())

@trace(name="my_agent")
def my_agent(query: str) -> str:
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[{"role": "user", "content": query}]
    )
    return response.content[0].text
```

### Google Gemini

```python
from google import genai
from verdictlens import configure, trace, wrap_google

configure(base_url="http://localhost:8000")
client = wrap_google(genai.Client(api_key="..."))

@trace(name="my_agent")
def my_agent(query: str) -> str:
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=query,
    )
    return response.text
```

### Parallel agents (asyncio.gather)

`contextvars` propagation means parallel branches maintain correct parent context automatically:

```python
@trace(name="parallel_analysis", span_type="agent")
async def parallel_analysis(items: list[str]) -> list:
    results = await asyncio.gather(
        *[analyze_item(item) for item in items]
    )
    return results
```

```
parallel_analysis (agent)
├── analyze_item (llm)  ← concurrent
├── analyze_item (llm)  ← concurrent
└── analyze_item (llm)  ← concurrent
```

---

## Provider support

### Auto-patchers (model + tokens + cost)

| Patcher | What it covers |
|---|---|
| `wrap_openai(client)` | OpenAI, Groq, xAI, Together, Fireworks, Azure OpenAI, Ollama, LM Studio, vLLM — anything OpenAI-compatible |
| `wrap_anthropic(client)` | All Claude models |
| `wrap_google(client)` | Gemini 1.5 Pro/Flash, Gemini 2.0 Flash |

If your provider isn't listed, `@trace` still works — you just won't get automatic token/cost capture. That's easy to add; PRs welcome.

### Built-in cost estimation

| Provider | Models |
|---|---|
| OpenAI | gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo |
| Anthropic | claude-3.5-sonnet, claude-3-opus, claude-3-haiku |
| Google | gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash |
| Groq | llama-3.3-70b, mixtral-8x7b, gemma2-9b |
| xAI | grok-3, grok-3-mini, grok-2 |

Unknown models trace safely — cost shows as `—`, nothing is dropped.

---

## Blame analysis

When a multi-agent pipeline fails, VerdictLens traverses the span tree to find the root cause.

```bash
GET /traces/{id}/blame
```

Every span gets classified:

| Role | What it means |
|---|---|
| **ORIGINATOR** | Introduced the bad state — null output, error, malformed data |
| **PROPAGATOR** | Received bad state and passed it downstream without fixing it |
| **MANIFESTOR** | Where the failure became visible — usually what you'd see in logs |
| **CLEAN** | Not involved |

The algorithm runs 5 passes:

1. **Intrinsic state** — mark each span's own errors/nulls
2. **Bottom-up aggregation** — roll up subtree failures
3. **Top-down propagation** — mark spans inheriting upstream failure
4. **Sibling propagation** — catch cross-branch data flow
5. **Role classification** — assign the final label

Confidence scores:

| Confidence | When |
|---|---|
| **high** | Score gap > 0.25 between top two suspects |
| **medium** | Gap between 0.10 and 0.25 |
| **ambiguous** | Gap < 0.10 — returns co-originators instead |

Handles retry storms, independent co-failures, pass-through propagators, and graceful recovery.

---

## Replay / time-travel debugging

Click **Replay** on any span. Edit the input. VerdictLens makes a real LLM call and shows side-by-side:

```
ORIGINAL                          REPLAY
─────────────────────────────────────────────
input: "quantum computing"        input: "machine learning"
output: null (error)              output: "ML is a subset of..."
latency: 201ms                    latency: 2152ms
cost: $0.0115                     cost: $0.0006
status: error                     status: success

Result: IMPROVED
```

For nested spans, VerdictLens reconstructs the parent execution context so the replayed call has the same environment as the original.

---

## Datasets & Evaluations

Save any trace or span as a labeled example. Run evals to score quality and compare versions.

### From code

```python
from verdictlens import create_dataset, add_example

ds = create_dataset("qa-golden-set")
add_example(ds["id"], inputs={"query": "What is AI?"}, expected={"answer": "..."})
```

Or click **Add to Dataset** on any trace in the UI.

### Run an evaluation

```python
from verdictlens import evaluate

result = evaluate(
    name="v2-quality-check",
    dataset_id="...",
    scorers=[
        {"type": "exact_match"},
        {"type": "contains", "field": "answer"},
        {"type": "llm_judge", "model": "gpt-4o-mini"},
    ],
    mode="replay",   # "live" for real LLM calls
)
```

Two modes:
- **replay** — scores stored outputs, no LLM calls, free
- **live** — calls your pipeline with real LLMs, captures new traces

---

## Prompt playground

Live editor for prompts. Tune model, temperature, max tokens, system message. Cmd+Enter to run.

Safety limits on every run (configurable via `.env`):
- Token clamping
- Rate limiting per workspace
- Cost guard per request
- Prompt sanitization

---

## Prompt hub

Version and share prompts across your team. Full history, publish/unpublish, one-click promote to roll back.

---

## Multi-workspace

Everything is namespaced by workspace + project:

```python
configure(
    base_url="http://localhost:8000",
    api_key="vdl_...",
    workspace="my-team",
    project="production",
)
```

API keys are SHA-256 hashed in PostgreSQL. Create and manage them from the UI.

---

## Architecture

```
Your agents ──→ SDK (@trace + auto-patchers) ──→ FastAPI API ──→ ClickHouse (traces, spans)
                    │                                    │    ├──→ PostgreSQL (auth, prompts)
                    │ contextvars span stack              │    └──→ Redis (pub/sub)
                    └─ wrap_openai / wrap_anthropic       │
                       wrap_google                   React Dashboard ←─┘
```

| Component | Tech | Why |
|---|---|---|
| SDK | Python, httpx, contextvars | Hierarchical spans, non-blocking, disk fallback |
| Auto-patchers | wrap_openai/anthropic/google | Zero-code LLM tracing |
| API | FastAPI | Auto OpenAPI docs, same language as SDK |
| Trace storage | ClickHouse | Columnar, handles 10k+ events/sec, fast aggregations |
| Transactional storage | PostgreSQL + Alembic | Workspaces, API keys, prompts, alerts |
| Pub/Sub | Redis | WebSocket fan-out across API replicas |
| Dashboard | React, Tailwind, Recharts | Recursive span tree, blame badges, replay |

---

## VerdictLens vs alternatives

Not trying to replace everything — just filling the gap that none of them cover.

| | VerdictLens | LangSmith | Langfuse | AgentOps |
|---|---|---|---|---|
| Open source | Yes (Apache 2.0) | No | Yes | Partial |
| Self-hostable | Yes, one command | No | Yes | No |
| Framework agnostic | Yes | LangChain-first | LangChain-first | Limited |
| Blame analysis | Yes (5-pass) | No | No | No |
| Replay debugging | Yes (real LLM) | No | No | No |
| Dataset builder | Yes | Yes | Yes | No |
| Evaluation engine | Yes | Yes | Yes | No |
| Prompt playground | Yes | Yes | No | No |
| Multi-workspace | Yes | Yes | Yes | No |
| Cost | Free, self-hosted | $39+/seat/mo | Free tier + paid | $20+/mo |

---

## Self-hosting

Requires Docker, 2GB RAM, 10GB disk.

```bash
docker compose up -d --build
```

Uses your local PostgreSQL by default. If you want the bundled Postgres instead:

```bash
docker compose --profile bundled-pg up -d --build
```

| Service | Port | Notes |
|---|---|---|
| Dashboard | 3000 | Exposed |
| API | 8000 | Exposed |
| ClickHouse | 8123, 9000 | Internal only |
| Redis | 6379 | Internal only |

Security defaults worth knowing:
- ClickHouse and Redis are not published to the host
- Auth is disabled by default (easy for local use, set `VERDICTLENS_API_KEY` for production)
- API keys are SHA-256 hashed
- Playground has rate limiting and cost guards

For production: put the API behind a reverse proxy with TLS, set `VERDICTLENS_REQUIRE_AUTH=true`, restrict `VERDICTLENS_CORS_ORIGINS`.

---

## API endpoints

### Traces

| Method | Path | |
|---|---|---|
| `POST` | `/traces` | Ingest |
| `GET` | `/traces` | List (paginated, filterable) |
| `GET` | `/traces/{id}` | Full trace + span tree |
| `GET` | `/traces/{id}/blame` | Blame analysis |
| `POST` | `/traces/{id}/spans/{sid}/replay` | Replay a span |
| `GET` | `/metrics` | Aggregated metrics |
| `WS` | `/live` | Real-time stream |

### Datasets & Evaluations

| Method | Path | |
|---|---|---|
| `POST/GET/DELETE` | `/datasets` | CRUD |
| `POST/GET/DELETE` | `/datasets/{id}/examples` | Examples |
| `POST` | `/traces/{id}/to-dataset` | Convert trace to example |
| `POST/GET/DELETE` | `/evaluations` | CRUD |
| `GET` | `/evaluations/compare` | Compare two runs |

### Playground & Prompt Hub

| Method | Path | |
|---|---|---|
| `POST` | `/playground/run` | Execute prompt |
| `POST/GET/DELETE` | `/playground/prompts` | Prompt versions |
| `GET` | `/playground/prompts/{name}/history` | Version history |
| `POST` | `/playground/prompts/{id}/publish` | Publish to hub |
| `GET` | `/prompt-hub` | Published prompts |

Full interactive docs at **http://localhost:8000/docs**.

---

## Configuration

Copy `.env.example` → `.env`. The important ones:

```bash
# Auth (off by default)
VERDICTLENS_API_KEY=your-secret
VERDICTLENS_REQUIRE_AUTH=true

# Storage
VERDICTLENS_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/verdictlens
VERDICTLENS_CH_HOST=clickhouse
VERDICTLENS_REDIS_URL=redis://redis:6379/0

# LLM keys (needed for Replay and Playground)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk-...

# Playground limits
VERDICTLENS_PLAYGROUND_MAX_TOKENS=4096
VERDICTLENS_PLAYGROUND_MAX_COST_USD=1.0

# CORS — restrict this in production
VERDICTLENS_CORS_ORIGINS=http://localhost:3000
```

---

## Try the demo

```bash
pip install -e ./sdk
python examples/demo.py
```

Generates 18 hierarchical traces with nested span trees, parallel async branches, and intentional failures — good for seeing blame analysis in action.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
cd sdk && pip install -e ".[dev]" && pytest
cd backend && pip install -e ".[dev]" && pytest
cd frontend && npm install && npm run dev
```

---

## License

Apache 2.0
