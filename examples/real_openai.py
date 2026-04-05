"""
VerdictLens + Real LLM integration (supports Grok/xAI, OpenAI, or any compatible API).

Prerequisites:
    pip install openai
    Add your key to .env:
        XAI_API_KEY=xai-...        (for Grok)
        OPENAI_API_KEY=sk-...      (for OpenAI)

Usage:
    cd verdictlens
    source .venv/bin/activate
    python examples/real_openai.py
"""

import os
import sys
from pathlib import Path

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value and key not in os.environ:
            os.environ[key] = value

from openai import OpenAI

from verdictlens import configure, trace
from verdictlens.integrations.openai import instrument_openai_client

configure(base_url="http://localhost:8000")

# ── Auto-detect provider: Groq > Grok (xAI) > OpenAI ───────────
groq_key = os.environ.get("GROQ_API_KEY")
xai_key = os.environ.get("XAI_API_KEY")
openai_key = os.environ.get("OPENAI_API_KEY")

if groq_key:
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
    MODEL = "llama-3.3-70b-versatile"
    PROVIDER = "Groq"
elif xai_key:
    client = OpenAI(base_url="https://api.x.ai/v1", api_key=xai_key)
    MODEL = "grok-4-1-fast"
    PROVIDER = "Grok (xAI)"
elif openai_key:
    client = OpenAI(api_key=openai_key)
    MODEL = "gpt-4o-mini"
    PROVIDER = "OpenAI"
else:
    print("ERROR: Set one of these in .env:")
    print("  GROQ_API_KEY=gsk-...     (free at https://console.groq.com/keys)")
    print("  XAI_API_KEY=xai-...      (https://console.x.ai)")
    print("  OPENAI_API_KEY=sk-...    (https://platform.openai.com)")
    sys.exit(1)

instrument_openai_client(client)


# ── Agent functions ─────────────────────────────────────────────

@trace(name="summarizer_agent", framework="openai")
def summarize(text: str) -> str:
    """Ask the LLM to summarize a block of text."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a concise summarizer. Reply in 2-3 sentences."},
            {"role": "user", "content": f"Summarize this:\n\n{text}"},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content


@trace(name="classifier_agent", framework="openai")
def classify(text: str) -> str:
    """Classify text into a category."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify the user message into exactly one category: "
                    "billing, technical, feature_request, bug_report, general. "
                    "Reply with the category name only."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


@trace(name="qa_agent", framework="openai")
def answer_question(question: str, context: str) -> str:
    """Answer a question given some context."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Answer the question based only on the provided context. Be concise.",
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content


# ── Run ─────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(f"  VerdictLens — Real Integration Test ({PROVIDER})")
    print(f"  Model:     {MODEL}")
    print(f"  Dashboard: http://localhost:3000")
    print("=" * 60)

    print("\n[1] Summarizer agent...")
    article = (
        "Artificial intelligence agents are autonomous software systems that can "
        "plan, reason, and take actions to achieve goals. In 2025-2026, they are "
        "being deployed across customer support, code review, data analysis, and "
        "research. However, observability remains a major gap — when agents fail, "
        "hallucinate, or spike costs, teams have no visibility into what went wrong. "
        "VerdictLens aims to fill this gap as the open-source Grafana for AI agents."
    )
    summary = summarize(article)
    print(f"    Summary: {summary}\n")

    print("[2] Classifier agent (3 messages)...")
    messages = [
        "My credit card was charged twice last month",
        "The API returns 500 errors when I send batch requests",
        "It would be great if you added dark mode to the dashboard",
    ]
    for msg in messages:
        label = classify(msg)
        print(f"    '{msg[:50]}...' -> {label}")

    print("\n[3] QA agent...")
    ctx = (
        "VerdictLens is an open-source AI agent observability platform. "
        "It provides a Python SDK with a @trace decorator, a FastAPI backend, "
        "ClickHouse for storage, and a React dashboard. It supports OpenAI, "
        "LangChain, CrewAI, AutoGen, and LlamaIndex frameworks."
    )
    answer = answer_question("What database does VerdictLens use?", ctx)
    print(f"    Answer: {answer}")

    from verdictlens import get_client
    print("\nFlushing traces...")
    get_client().flush(timeout=5.0)

    print("\n" + "=" * 60)
    print(f"  Done! 6 real {PROVIDER} traces sent to VerdictLens.")
    print("  Check http://localhost:3000/traces to see them.")
    print("=" * 60)


if __name__ == "__main__":
    main()
