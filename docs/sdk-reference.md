# SDK Reference

## Installation

```bash
pip install verdictlens
```

With framework extras:

```bash
pip install verdictlens[openai]       # OpenAI (for type stubs)
pip install verdictlens[all]          # Everything
```

---

## Core API

### `configure(**kwargs) → VerdictLensConfig`

Set global SDK configuration. Call once at startup.

```python
from verdictlens import configure

configure(
    base_url="http://localhost:8000",  # Backend URL (default: http://127.0.0.1:8000)
    api_key="your-key",                # Optional Bearer token
    disabled=False,                     # Set True to make SDK a no-op
    timeout_seconds=10.0,              # HTTP timeout per request
    queue_dir="/tmp/verdictlens-queue",  # Offline queue directory
    max_queue_bytes=256 * 1024 * 1024, # Max offline queue size (256 MB)
)
```

**Environment variable overrides** (no code changes needed):

| Variable | Maps to |
|---|---|
| `VERDICTLENS_BASE_URL` | `base_url` |
| `VERDICTLENS_API_KEY` | `api_key` |
| `VERDICTLENS_DISABLED` | `disabled` |
| `VERDICTLENS_QUEUE_DIR` | `queue_dir` |

---

### `@trace` decorator

Wrap any sync or async function to record a span. Nested `@trace` calls automatically form parent-child trees via `contextvars`.

```python
from verdictlens import trace

@trace(name="my_pipeline", span_type="chain")
def pipeline(query: str) -> str:
    result = sub_agent(query)   # automatically becomes a child span
    return result

@trace(name="sub_agent", span_type="agent")
def sub_agent(query: str) -> str:
    return "answer"

@trace(name="async_agent")
async def run_async(query: str) -> str:
    return await get_answer(query)
```

**Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `module:qualname` | Span name shown in the dashboard |
| `span_type` | `str` | `"agent"` | One of: `agent`, `llm`, `tool`, `chain`, `retrieval`, `other` |
| `framework` | `str \| None` | `None` | Framework label (e.g., `"openai"`, `"langchain"`) |
| `model` | `str \| None` | `None` | Static model override when not inferable from output |
| `decision` | `str \| None` | `None` | Why the agent took this action |
| `capture_args` | `bool` | `True` | Include function arguments in the span |
| `capture_result` | `bool` | `True` | Include return value in the span |

**How nesting works:**

1. The outermost `@trace` creates a **root span** and a **trace envelope**.
2. Any `@trace` called inside another `@trace` becomes a **child span** — `parent_span_id` is set automatically.
3. All child spans are collected and emitted as a single trace when the root span completes.
4. Token usage and cost from all child spans are aggregated to the trace header.
5. Works across `asyncio.gather`, `asyncio.create_task`, and nested sync/async calls.

**What gets captured automatically:**

- Function input arguments (JSON-serialized, truncated at 16 KB)
- Return value (JSON-serialized, truncated at 16 KB)
- Wall-clock latency in milliseconds
- Errors (exception type + message + stack; exception is re-raised)
- Token usage (if return value has `.usage` or `["usage"]`)
- Model name (if return value has `.model` or `["model"]`)
- Estimated cost (USD, from built-in pricing table)

---

### `wrap_openai(client) → client`

Patch an OpenAI client so `chat.completions.create` auto-creates child spans under the active `@trace` context.

```python
from openai import OpenAI, AsyncOpenAI
from verdictlens import wrap_openai

client = wrap_openai(OpenAI())
async_client = wrap_openai(AsyncOpenAI())

@trace(name="my_agent")
def my_agent(query: str) -> str:
    # This call auto-creates a child span: "openai.chat.completions.create(gpt-4o)"
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": query}]
    )
    return response.choices[0].message.content
```

**What gets captured:**

- Model name, temperature, max_tokens
- Input messages (serialized)
- Output content
- Token usage (prompt, completion, total)
- Cost estimate (USD)
- Latency
- Errors

**Idempotent** — safe to call multiple times. **No-op outside `@trace`** — if called without an active trace context, the original method runs unmodified.

---

### `wrap_anthropic(client) → client`

Patch an Anthropic client so `messages.create` auto-creates child spans.

```python
from anthropic import Anthropic, AsyncAnthropic
from verdictlens import wrap_anthropic

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

Maps `input_tokens` / `output_tokens` to the standard `prompt_tokens` / `completion_tokens` schema.

---

### `wrap_google(client) → client`

Patch a `google.genai.Client` so `models.generate_content` auto-creates child spans. Patches both sync (`client.models`) and async (`client.aio.models`).

```python
from google import genai
from verdictlens import wrap_google

client = wrap_google(genai.Client(api_key="..."))

@trace(name="my_agent")
def my_agent(query: str) -> str:
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=query,
    )
    return response.text
```

**What gets captured:**

- Model name, config (temperature, top_p, etc.)
- Input contents (serialized)
- Output text
- Token usage (prompt_token_count, candidates_token_count, total_token_count)
- Cost estimate (USD) for gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash
- Latency
- Errors

**Idempotent** — safe to call multiple times. **No-op outside `@trace`**.

---

### `get_current_span()`

Return the active span context, or `None` if no trace is active. Useful for advanced instrumentation.

```python
from verdictlens import get_current_span

span = get_current_span()
if span:
    print(f"Inside trace: {span.trace_id}, span: {span.span_id}")
```

---

### `record_child_span(**kwargs) → str | None`

Programmatically add a child span under the active trace context. Used internally by `wrap_openai` / `wrap_anthropic` / `wrap_google`, but available for custom integrations.

```python
from verdictlens import record_child_span

span_id = record_child_span(
    name="custom_llm_call",
    span_type="llm",
    model="my-model",
    input_data={"prompt": "hello"},
    output_data={"response": "world"},
    latency_ms=150.0,
    token_usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    cost_usd=0.001,
)
```

Returns the span_id, or `None` if no active trace context.

---

### `set_cost_estimator(fn)`

Replace the default cost estimation function.

```python
from verdictlens import set_cost_estimator, per_million_table

set_cost_estimator(per_million_table({
    "gpt-4o": (5.0, 15.0),        # (input_per_1M, output_per_1M) in USD
    "gpt-4o-mini": (0.15, 0.60),
    "claude-3-opus": (15.0, 75.0),
}))
```

---

## Transport & Reliability

The SDK never blocks your application:

1. **Async background thread** — traces are enqueued in-memory and POSTed by a dedicated thread
2. **Automatic retries** — 3 retries with exponential backoff (50ms → 200ms → 750ms)
3. **Offline queue** — if the backend is unreachable after retries, payloads are written to `~/.verdictlens/queue/` as JSONL files
4. **Background flush** — a second thread periodically retries queued files every 2 seconds
5. **Bounded memory** — in-memory queue capped at 50,000 items; disk queue capped at 256 MB

### Graceful shutdown

```python
from verdictlens import get_client

# Flush pending traces before exit (blocks up to 5s)
get_client().flush(timeout=5.0)
```

---

## Trace Payload Schema

Every trace sent to `POST /traces` follows this structure. Spans form a tree via `parent_span_id`.

```json
{
  "trace_id": "uuid",
  "name": "research_pipeline",
  "start_time": "2026-03-25T12:00:00Z",
  "end_time": "2026-03-25T12:00:03Z",
  "latency_ms": 3000.0,
  "status": "success",
  "framework": "verdictlens",
  "model": "gpt-4o",
  "input": { "args": [...], "kwargs": { "topic": "AI safety" } },
  "output": { "findings": "...", "review": "..." },
  "token_usage": {
    "prompt_tokens": 2500,
    "completion_tokens": 800,
    "total_tokens": 3300
  },
  "cost_usd": 0.0245,
  "error": null,
  "spans": [
    {
      "span_id": "uuid-1",
      "parent_span_id": null,
      "name": "research_pipeline",
      "span_type": "chain",
      "latency_ms": 3000.0,
      "metadata": { "span_role": "root" }
    },
    {
      "span_id": "uuid-2",
      "parent_span_id": "uuid-1",
      "name": "rag_agent",
      "span_type": "agent",
      "latency_ms": 1500.0,
      "metadata": { "span_role": "child" }
    },
    {
      "span_id": "uuid-3",
      "parent_span_id": "uuid-2",
      "name": "openai.chat.completions.create(gpt-4o)",
      "span_type": "llm",
      "model": "gpt-4o",
      "token_usage": { "prompt_tokens": 1200, "completion_tokens": 400, "total_tokens": 1600 },
      "cost_usd": 0.012,
      "metadata": { "span_role": "auto" }
    },
    {
      "span_id": "uuid-4",
      "parent_span_id": "uuid-1",
      "name": "review_agent",
      "span_type": "agent",
      "latency_ms": 1200.0,
      "metadata": { "span_role": "child" }
    }
  ],
  "metadata": { "sdk": "verdictlens", "python": "3.12.0", "schema_version": "2.0.0" }
}
```

Span types: `agent`, `llm`, `tool`, `chain`, `retrieval`, `other`.

Span roles in metadata: `root` (outermost @trace), `child` (nested @trace), `auto` (from auto-patchers).

---

## Edge Cases

| Scenario | Behavior |
|---|---|
| `@trace` inside `@trace` | Child span, auto-linked via `parent_span_id` |
| `asyncio.gather` with `@trace` | Each branch maintains correct parent via `contextvars` |
| `@trace` in a raw `threading.Thread` | Context does NOT propagate — use `contextvars.copy_context().run()` |
| `wrap_openai`/`wrap_google` call outside `@trace` | Original method runs unmodified, no span created |
| `wrap_openai`/`wrap_google` called twice | Idempotent, second call is a no-op |
| Exception in `@trace` | Error recorded on span, exception re-raised, trace status set to "error" |
| Streaming completions (`stream=True`) | Call is traced but token usage may not be available until stream completes |
