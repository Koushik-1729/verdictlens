# verdictlens (Python SDK)

Python client for **VerdictLens** — hierarchical tracing for AI agent workloads with auto-instrumentation.

See the repository root for the full platform quickstart.

## Install

```bash
pip install verdictlens
```

## Quickstart

```python
from verdictlens import configure, trace, wrap_openai
from openai import OpenAI

configure(base_url="http://localhost:8000")
client = wrap_openai(OpenAI())

@trace(name="my_pipeline", span_type="chain")
def my_pipeline(query: str) -> str:
    context = retrieve(query)
    return generate(context, query)

@trace(name="retrieve", span_type="retrieval")
def retrieve(query: str) -> list:
    return vector_db.search(query)

@trace(name="generate", span_type="agent")
def generate(context: list, query: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"{context}\n{query}"}]
    )
    return response.choices[0].message.content
```

This produces a hierarchical span tree:

```
my_pipeline (chain)
├── retrieve (retrieval)
└── generate (agent)
    └── openai.chat.completions.create(gpt-4o-mini) (llm)  ← auto-traced
```

## Key Features

- **Nested `@trace`** — child spans auto-attach to parent via `contextvars`
- **`wrap_openai(client)`** — auto-trace OpenAI chat completions with zero code
- **`wrap_anthropic(client)`** — auto-trace Anthropic messages with zero code
- **`wrap_google(client)`** — auto-trace Google Gemini `generate_content` with zero code
- **`asyncio.gather` safe** — parallel branches maintain correct parent context
- **Non-blocking** — async transport with disk-backed offline queue
