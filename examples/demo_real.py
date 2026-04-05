"""
VerdictLens real LLM demo — uses actual Groq API calls.

Usage:
    pip install -e ./sdk openai
    python examples/demo_real.py

Requires GROQ_API_KEY in your environment or .env file.
"""

import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

from openai import OpenAI, AsyncOpenAI
from verdictlens import configure, trace, wrap_openai, get_client

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not set. Get one free at https://console.groq.com/keys")

configure(base_url="http://localhost:8000")

sync_client = wrap_openai(OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
))

async_client = wrap_openai(AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
))

MODEL = "llama-3.1-8b-instant"


# ---------------------------------------------------------------------------
# Trace 1: Simple single-agent Q&A
# ---------------------------------------------------------------------------

@trace(name="simple_qa", span_type="agent")
def simple_qa(question: str) -> str:
    response = sync_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": question}],
        max_tokens=200,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Trace 2: Research pipeline (2 levels deep)
# ---------------------------------------------------------------------------

@trace(name="research_pipeline", span_type="chain")
def research_pipeline(topic: str) -> dict:
    findings = research_agent(topic)
    summary = summary_agent(findings)
    return {"findings": findings, "summary": summary}


@trace(name="research_agent", span_type="agent")
def research_agent(topic: str) -> str:
    response = sync_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a research assistant. Give 3 key facts."},
            {"role": "user", "content": f"Research this topic: {topic}"},
        ],
        max_tokens=300,
    )
    return response.choices[0].message.content


@trace(name="summary_agent", span_type="agent")
def summary_agent(findings: str) -> str:
    response = sync_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Summarize the research findings in 2 sentences."},
            {"role": "user", "content": findings},
        ],
        max_tokens=150,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Trace 3: Multi-agent debate (3 levels deep)
# ---------------------------------------------------------------------------

@trace(name="debate_pipeline", span_type="chain")
def debate_pipeline(topic: str) -> dict:
    pro = argument_agent(topic, "for")
    con = argument_agent(topic, "against")
    verdict = judge_agent(topic, pro, con)
    return {"pro": pro, "con": con, "verdict": verdict}


@trace(name="argument_agent", span_type="agent")
def argument_agent(topic: str, stance: str) -> str:
    response = sync_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": f"Argue {stance} the following topic. Be concise (2-3 sentences)."},
            {"role": "user", "content": topic},
        ],
        max_tokens=200,
    )
    return response.choices[0].message.content


@trace(name="judge_agent", span_type="agent")
def judge_agent(topic: str, pro: str, con: str) -> str:
    response = sync_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are an impartial judge. Pick the stronger argument and explain why in 1 sentence."},
            {"role": "user", "content": f"Topic: {topic}\n\nFor: {pro}\n\nAgainst: {con}"},
        ],
        max_tokens=150,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Trace 4: Parallel async analysis
# ---------------------------------------------------------------------------

@trace(name="parallel_analysis", span_type="chain")
async def parallel_analysis(items: list[str]) -> list[str]:
    results = await asyncio.gather(*[analyze_item(item) for item in items])
    return list(results)


@trace(name="analyze_item", span_type="agent")
async def analyze_item(item: str) -> str:
    response = await async_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Give a one-sentence analysis."},
            {"role": "user", "content": f"Analyze: {item}"},
        ],
        max_tokens=100,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Trace 5: Intentional failure (for blame analysis)
# ---------------------------------------------------------------------------

@trace(name="flaky_pipeline", span_type="chain")
def flaky_pipeline(query: str) -> dict:
    step1 = flaky_retriever(query)
    step2 = flaky_generator(step1)
    return {"retrieval": step1, "generation": step2}


@trace(name="retriever", span_type="retrieval")
def flaky_retriever(query: str) -> str:
    return None


@trace(name="generator", span_type="agent")
def flaky_generator(context) -> str:
    response = sync_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Summarize the context provided."},
            {"role": "user", "content": str(context)},
        ],
        max_tokens=150,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Run all traces
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  VerdictLens Real LLM Demo (Groq API)")
    print(f"  Model: {MODEL}")
    print("  Dashboard: http://localhost:3000")
    print("=" * 60)

    print("\n[1/5] Simple Q&A...")
    result = simple_qa("What are the three laws of thermodynamics?")
    print(f"  → {result[:80]}...")

    print("\n[2/5] Research pipeline (2-level span tree)...")
    result = research_pipeline("quantum computing")
    print(f"  → Summary: {result['summary'][:80]}...")

    print("\n[3/5] Debate pipeline (3-level span tree)...")
    result = debate_pipeline("AI will replace most software engineers within 10 years")
    print(f"  → Verdict: {result['verdict'][:80]}...")

    print("\n[4/5] Parallel async analysis (concurrent spans)...")
    items = ["Bitcoin price trends", "Climate change policy", "Remote work productivity"]
    results = asyncio.run(parallel_analysis(items))
    for item, r in zip(items, results):
        print(f"  → {item}: {r[:60]}...")

    print("\n[5/5] Flaky pipeline (will produce null — for blame testing)...")
    try:
        result = flaky_pipeline("explain gravity")
        print(f"  → {str(result)[:80]}...")
    except Exception as e:
        print(f"  → Error (expected): {e}")

    print("\nFlushing traces...")
    get_client().flush(timeout=10.0)

    print("\n" + "=" * 60)
    print("  Done! All traces used REAL Groq LLM calls.")
    print("  Check: http://localhost:3000/traces")
    print("=" * 60)


if __name__ == "__main__":
    main()
