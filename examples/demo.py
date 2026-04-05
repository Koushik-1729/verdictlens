"""
VerdictLens live demo — generates hierarchical agent traces.

Demonstrates nested @trace spans, auto-patchers, and asyncio.gather,
all producing parent-child span trees.

Usage:
    cd verdictlens
    pip install ./sdk
    python examples/demo.py

Sends ~20 traces with nested spans so you can see the dashboard,
live feed, cost tracker, blame analysis, and span tree populate.
"""

import random
import time
import asyncio
from verdictlens import configure, trace, get_client

configure(base_url="http://localhost:8000")


# ---------------------------------------------------------------------------
# Leaf agents — these are the innermost spans
# ---------------------------------------------------------------------------

@trace(name="llm_call", span_type="llm")
def llm_call(prompt: str, model: str = "gpt-4o-mini") -> dict:
    """Simulate an LLM call (leaf span)."""
    time.sleep(random.uniform(0.05, 0.3))
    tokens = {
        "prompt_tokens": random.randint(100, 500),
        "completion_tokens": random.randint(50, 300),
    }
    tokens["total_tokens"] = tokens["prompt_tokens"] + tokens["completion_tokens"]
    return {
        "content": f"Response to: {prompt[:50]}...",
        "model": model,
        "usage": tokens,
    }


@trace(name="retrieval", span_type="retrieval")
def retrieve_context(query: str) -> dict:
    """Simulate a vector store lookup (leaf span)."""
    time.sleep(random.uniform(0.02, 0.1))
    return {
        "documents": [f"Doc about {query[:30]}...", f"Related: {query[:20]}..."],
        "scores": [round(random.uniform(0.7, 0.99), 3), round(random.uniform(0.5, 0.85), 3)],
    }


@trace(name="tool_call", span_type="tool")
def run_tool(tool_name: str, args: dict) -> dict:
    """Simulate an external tool call (leaf span)."""
    time.sleep(random.uniform(0.01, 0.1))
    if random.random() < 0.15:
        raise RuntimeError(f"Tool '{tool_name}' timed out")
    return {"result": f"{tool_name} executed successfully", "args": args}


# ---------------------------------------------------------------------------
# Mid-level agents — compose leaf spans
# ---------------------------------------------------------------------------

@trace(name="rag_agent", span_type="chain")
def rag_agent(query: str) -> dict:
    """RAG pipeline: retrieve → generate. Produces a 2-level span tree."""
    context = retrieve_context(query)
    docs = context.get("documents", [])
    prompt = f"Context: {docs}\n\nQuestion: {query}\n\nAnswer:"
    response = llm_call(prompt, model="gpt-4o")
    return {"answer": response["content"], "sources": docs}


@trace(name="planning_agent", span_type="agent")
def planning_agent(goal: str) -> dict:
    """Plan → execute tools → summarize. Produces a 3-level tree."""
    plan = llm_call(f"Create a plan for: {goal}", model="gpt-4o")
    steps = [f"step_{i}" for i in range(random.randint(2, 4))]
    results = []
    for step in steps:
        try:
            result = run_tool(step, {"goal": goal})
            results.append(result)
        except RuntimeError:
            results.append({"error": f"{step} failed"})
    summary = llm_call(
        f"Summarize results for {goal}: {results}",
        model="gpt-4o-mini",
    )
    return {"plan": plan["content"], "results": results, "summary": summary["content"]}


@trace(name="review_agent", span_type="agent")
def review_agent(content: str) -> dict:
    """Review content with a quality check. 2-level tree."""
    review = llm_call(f"Review this content: {content[:200]}", model="gpt-4o")
    quality = llm_call(
        f"Rate quality 1-10: {review['content'][:100]}",
        model="gpt-4o-mini",
    )
    return {"review": review["content"], "quality": quality["content"]}


# ---------------------------------------------------------------------------
# Top-level orchestrators — produce deep trees
# ---------------------------------------------------------------------------

@trace(name="research_pipeline", span_type="chain", framework="verdictlens")
def research_pipeline(topic: str) -> dict:
    """Full research pipeline: RAG → planning → review. 4-level tree."""
    findings = rag_agent(f"Research: {topic}")
    plan = planning_agent(f"Deep dive into: {topic}")
    review = review_agent(findings["answer"])
    return {
        "topic": topic,
        "findings": findings["answer"],
        "plan": plan["summary"],
        "review": review["review"],
    }


@trace(name="support_pipeline", span_type="chain", framework="verdictlens")
def support_pipeline(query: str) -> dict:
    """Customer support: classify → RAG → respond. 3-level tree."""
    classification = llm_call(f"Classify: {query}", model="gpt-4o-mini")
    answer = rag_agent(query)
    return {"classification": classification["content"], "answer": answer["answer"]}


@trace(name="flaky_pipeline", span_type="chain", framework="verdictlens")
def flaky_pipeline(task: str) -> dict:
    """Pipeline that sometimes fails at a nested level. Produces error trees."""
    plan = llm_call(f"Plan: {task}", model="gpt-4o-mini")
    tool_result = run_tool("critical_tool", {"task": task})
    summary = llm_call(f"Summarize: {tool_result}", model="gpt-4o-mini")
    return {"plan": plan["content"], "tool": tool_result, "summary": summary["content"]}


# ---------------------------------------------------------------------------
# Async nested traces — demonstrates asyncio.gather with parent context
# ---------------------------------------------------------------------------

@trace(name="async_llm_call", span_type="llm")
async def async_llm_call(prompt: str, model: str = "gpt-4o-mini") -> dict:
    """Async leaf LLM call."""
    await asyncio.sleep(random.uniform(0.02, 0.15))
    tokens = {
        "prompt_tokens": random.randint(50, 200),
        "completion_tokens": random.randint(20, 100),
    }
    tokens["total_tokens"] = tokens["prompt_tokens"] + tokens["completion_tokens"]
    return {"content": f"Async response: {prompt[:40]}", "model": model, "usage": tokens}


@trace(name="parallel_analysis", span_type="agent", framework="verdictlens")
async def parallel_analysis(items: list[str]) -> dict:
    """
    Analyze multiple items in parallel with asyncio.gather.
    Each gather branch maintains correct parent context via contextvars.
    """
    results = await asyncio.gather(
        *[async_llm_call(f"Analyze: {item}") for item in items]
    )
    summary = await async_llm_call(
        f"Summarize {len(results)} analyses",
        model="gpt-4o",
    )
    return {
        "analyses": [r["content"] for r in results],
        "summary": summary["content"],
    }


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------

TOPICS = [
    "transformer architectures 2026",
    "RAG vs fine-tuning comparison",
    "AI agent safety frameworks",
    "multi-agent coordination patterns",
]

QUERIES = [
    "How do I reset my password?",
    "My invoice is wrong",
    "Can't connect to the API",
    "Feature request: dark mode",
    "App crashes on startup",
]

TASKS = [
    "Summarize the meeting notes",
    "Draft a response email",
    "Generate test cases",
    "Analyze competitor pricing",
    "Create onboarding checklist",
]

ITEMS = [
    ["revenue Q1", "revenue Q2", "revenue Q3"],
    ["user growth", "churn rate", "NPS score"],
    ["latency p50", "latency p99", "error rate"],
]


def run_demo():
    """Send a mix of hierarchical traces to populate the dashboard."""
    print("=" * 60)
    print("  VerdictLens Live Demo (Hierarchical Traces)")
    print("  Sending traces to http://localhost:8000")
    print("  Open http://localhost:3000 to watch the dashboard")
    print("=" * 60)
    print()

    traces_sent = 0
    errors = 0

    # Round 1: Research pipelines (deep 4-level trees)
    print("[1/5] Research pipelines — 3 traces (4-level span trees)...")
    for topic in random.sample(TOPICS, 3):
        research_pipeline(topic)
        traces_sent += 1
        time.sleep(0.3)

    # Round 2: Support pipelines (3-level trees)
    print("[2/5] Support pipelines — 4 traces (3-level span trees)...")
    for query in random.sample(QUERIES, 4):
        support_pipeline(query)
        traces_sent += 1
        time.sleep(0.3)

    # Round 3: Flaky pipelines (error trees with nested failures)
    print("[3/5] Flaky pipelines — 5 traces (some will fail at nested level)...")
    for task in random.sample(TASKS, 5):
        try:
            flaky_pipeline(task)
        except RuntimeError:
            errors += 1
        traces_sent += 1
        time.sleep(0.3)

    # Round 4: Planning agents (3-level trees with tool spans)
    print("[4/5] Planning agents — 3 traces (3-level trees with tools)...")
    for task in random.sample(TASKS, 3):
        try:
            planning_agent(task)
        except RuntimeError:
            errors += 1
        traces_sent += 1
        time.sleep(0.3)

    # Round 5: Async parallel analysis (demonstrates asyncio.gather)
    print("[5/5] Async parallel analysis — 3 traces (parallel child spans)...")

    async def run_async_batch():
        for items in ITEMS:
            await parallel_analysis(items)

    asyncio.run(run_async_batch())
    traces_sent += 3

    # Flush
    print()
    print("Flushing traces to backend...")
    get_client().flush(timeout=5.0)
    time.sleep(1.0)

    print()
    print("=" * 60)
    print(f"  Done! Sent {traces_sent} traces ({errors} errors)")
    print(f"  Each trace contains nested parent-child span trees.")
    print()
    print("  Now check:")
    print("    Dashboard:  http://localhost:3000")
    print("    Traces:     http://localhost:3000/traces")
    print("    Live Feed:  http://localhost:3000/live")
    print("    Costs:      http://localhost:3000/costs")
    print("    Blame:      http://localhost:3000/blame")
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
