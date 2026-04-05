"""
Multi-agent Blame Analysis — Real NVIDIA NIM LLM Calls
=======================================================
Tests that:
  1. @trace propagates source_span_ids across real LLM-driven agents
  2. Backend blame API returns correct ORIGINATOR / MANIFESTOR roles
  3. Data-flow lineage (Option B) works end-to-end with real objects

Scenarios
---------
  A. Research → Planner → Executor  (research fails, planner and executor
     get MANIFESTOR role because their inputs came from the failed agent)

  B. Clean pipeline (all agents succeed → no blame expected)

  C. Parallel workers → merge agent  (worker_a fails, merge gets MANIFESTOR)

Usage:
    cd /path/to/agenetlens
    pip install -e ./sdk openai requests rich
    python examples/test_blame_nvidia.py
"""

import json
import os
import sys
import time
import requests
from datetime import datetime

from openai import OpenAI
from rich.console import Console
from rich.table import Table

# ── VerdictLens SDK ──────────────────────────────────────────────
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "sdk"))
from verdictlens import configure, trace, wrap_openai
from verdictlens.client import get_client

BASE_URL = "http://localhost:8000"
configure(base_url=BASE_URL, disabled=False, reset_client=True)

# ── NVIDIA NIM client ────────────────────────────────────────────
_nvidia_api_key = os.environ.get("NVIDIA_API_KEY")
if not _nvidia_api_key:
    raise EnvironmentError("NVIDIA_API_KEY environment variable is not set")

_nvidia_client = wrap_openai(OpenAI(
    base_url = "https://integrate.api.nvidia.com/v1",
    api_key = _nvidia_api_key,
))
MODEL = "google/gemma-2-9b-it"

console = Console()

# ── Results tracking ─────────────────────────────────────────────
checks_passed = 0
checks_failed = 0
check_log = []

def check(label: str, cond: bool, detail: str = ""):
    global checks_passed, checks_failed
    if cond:
        checks_passed += 1
        console.print(f"  [green]✓[/green] {label}")
    else:
        checks_failed += 1
        msg = f"  [red]✗[/red] {label}"
        if detail:
            msg += f"\n      [dim]{detail}[/dim]"
        console.print(msg)
    check_log.append({"label": label, "passed": cond, "detail": detail})


def llm(prompt: str, max_tokens: int = 256, system: str | None = None) -> str:
    """Single LLM call, returns text."""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    resp = _nvidia_client.chat.completions.create(
        model=MODEL,
        messages=msgs,
        max_tokens=max_tokens,
        temperature=0.2,
        stream=False,
    )
    return resp.choices[0].message.content or ""


def wait_for_trace(name: str, timeout: int = 15) -> str | None:
    """Poll /traces until a trace with the given name appears; return trace_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/traces", params={"name": name, "page_size": 5})
        if r.ok:
            rows = r.json().get("traces", [])
            if rows:
                return rows[0]["trace_id"]
        time.sleep(1)
    return None


# ══════════════════════════════════════════════════════════════════
# SCENARIO A  — Research fails → Planner + Executor are MANIFESTOR
# ══════════════════════════════════════════════════════════════════

console.rule("[bold cyan]Scenario A · Research agent fails, downstream agents are victims")

@trace(name="research_agent", span_type="agent")
def research_agent_failing(topic: str) -> str | None:
    """Makes a real LLM call but we intentionally discard the output to simulate failure."""
    # Real LLM call so the span has token usage and latency
    raw = llm(f"Find 3 facts about: {topic}", max_tokens=128)
    console.print(f"  [dim]research_agent got {len(raw)} chars from LLM[/dim]")
    # Simulate that the agent's post-processing crashed and returned None
    return None


@trace(name="planner_agent", span_type="agent")
def planner_agent(research_output: str | None) -> str | None:
    """Receives research output and builds a plan."""
    if research_output is None:
        raise ValueError("Cannot plan: research output was None")
    return llm(f"Build a 3-step plan based on: {research_output}", max_tokens=200)


@trace(name="executor_agent", span_type="agent")
def executor_agent(plan: str | None) -> str | None:
    """Executes a plan returned by the planner."""
    if plan is None:
        raise ValueError("Cannot execute: plan was None")
    return llm(f"Execute this plan and summarize results: {plan}", max_tokens=256)


@trace(name="pipeline_scenario_a", span_type="agent")
def run_scenario_a():
    research = research_agent_failing("distributed tracing in AI agents")
    plan = None
    try:
        plan = planner_agent(research)
    except Exception as e:
        console.print(f"  [dim]planner raised (expected): {e}[/dim]")
    result = None
    try:
        result = executor_agent(plan)
    except Exception as e:
        console.print(f"  [dim]executor raised (expected): {e}[/dim]")
    return result


run_scenario_a()
get_client().flush(timeout=8.0)
console.print("  [dim]flushed — waiting for ingestion...[/dim]")

tid_a = wait_for_trace("pipeline_scenario_a")
check("Scenario A trace ingested", tid_a is not None, "pipeline_scenario_a not found")

if tid_a:
    # Verify spans have source_span_ids
    detail = requests.get(f"{BASE_URL}/traces/{tid_a}").json()
    spans = {s["name"]: s for s in detail.get("spans", [])}

    check("research_agent span present", "research_agent" in spans)
    check("planner_agent span present",  "planner_agent"  in spans)
    check("executor_agent span present", "executor_agent" in spans)

    if "research_agent" in spans and "planner_agent" in spans:
        research_id = spans["research_agent"]["span_id"]
        planner_sources = spans["planner_agent"].get("source_span_ids", [])
        check(
            "planner_agent.source_span_ids → research_agent",
            research_id in planner_sources,
            f"planner source_span_ids={planner_sources}, research_id={research_id}",
        )

    if "planner_agent" in spans and "executor_agent" in spans:
        planner_id = spans["planner_agent"]["span_id"]
        executor_sources = spans["executor_agent"].get("source_span_ids", [])
        check(
            "executor_agent.source_span_ids → planner_agent",
            planner_id in executor_sources,
            f"executor source_span_ids={executor_sources}, planner_id={planner_id}",
        )

    # Blame API
    blame_resp = requests.get(f"{BASE_URL}/traces/{tid_a}/blame")
    check("blame API returns 200", blame_resp.status_code == 200, blame_resp.text[:200])

    if blame_resp.ok:
        blame = blame_resp.json()
        orig_names  = [o["span_name"] for o in blame.get("originators", [])]
        fail_names  = [f["span_name"] for f in blame.get("failure_points", [])]
        conf        = blame.get("confidence", "?")

        check("research_agent is ORIGINATOR", "research_agent" in orig_names,
              f"originators={orig_names}")
        check("planner_agent is MANIFESTOR",  "planner_agent"  in fail_names,
              f"failure_points={fail_names}")
        check("executor_agent is MANIFESTOR", "executor_agent" in fail_names,
              f"failure_points={fail_names}")
        check("confidence is not ambiguous",  conf in ("high", "medium"),
              f"confidence={conf}")

        console.print(f"\n  [bold]Human summary:[/bold] {blame.get('human_summary', '')}")
        console.print(f"  [bold]Propagation chain:[/bold]")
        for step in blame.get("propagation_chain", []):
            console.print(f"    → {step}")


# ══════════════════════════════════════════════════════════════════
# SCENARIO B  — Clean pipeline (all succeed, no blame expected)
# ══════════════════════════════════════════════════════════════════

console.print()
console.rule("[bold cyan]Scenario B · Clean pipeline — all agents succeed")


@trace(name="clean_researcher", span_type="agent")
def clean_researcher(topic: str) -> str:
    return llm(f"Give 2 key facts about: {topic}", max_tokens=128)


@trace(name="clean_planner", span_type="agent")
def clean_planner(facts: str) -> str:
    return llm(f"Create a short action plan using these facts:\n{facts}", max_tokens=128)


@trace(name="clean_executor", span_type="agent")
def clean_executor(plan: str) -> str:
    return llm(f"Summarize this plan in one sentence:\n{plan}", max_tokens=64)


@trace(name="pipeline_scenario_b", span_type="agent")
def run_scenario_b():
    facts = clean_researcher("observability in microservices")
    plan  = clean_planner(facts)
    return clean_executor(plan)


run_scenario_b()
get_client().flush(timeout=8.0)
console.print("  [dim]flushed — waiting for ingestion...[/dim]")

tid_b = wait_for_trace("pipeline_scenario_b")
check("Scenario B trace ingested", tid_b is not None)

if tid_b:
    detail_b = requests.get(f"{BASE_URL}/traces/{tid_b}").json()
    check("trace status is success",
          detail_b.get("status") == "success",
          f"status={detail_b.get('status')}")

    # Clean trace → blame should return 404 (no bad spans)
    blame_b = requests.get(f"{BASE_URL}/traces/{tid_b}/blame")
    check("clean trace returns no blame (404 or empty)",
          blame_b.status_code == 404 or not blame_b.json().get("originators"),
          f"status={blame_b.status_code}")

    # Verify source_span_ids still tracked even on clean runs
    spans_b = {s["name"]: s for s in detail_b.get("spans", [])}
    if "clean_researcher" in spans_b and "clean_planner" in spans_b:
        researcher_id = spans_b["clean_researcher"]["span_id"]
        planner_sources_b = spans_b["clean_planner"].get("source_span_ids", [])
        check(
            "clean pipeline: planner still tracks researcher via source_span_ids",
            researcher_id in planner_sources_b,
            f"source_span_ids={planner_sources_b}",
        )


# ══════════════════════════════════════════════════════════════════
# SCENARIO C  — Parallel workers, one fails → merge is MANIFESTOR
# ══════════════════════════════════════════════════════════════════

console.print()
console.rule("[bold cyan]Scenario C · Worker A fails, merge agent is MANIFESTOR")


@trace(name="worker_a_llm", span_type="agent")
def worker_a(topic: str) -> str | None:
    """Makes a real LLM call then simulates a crash."""
    llm(f"Research aspect A of: {topic}", max_tokens=96)
    return None  # simulated crash return


@trace(name="worker_b_llm", span_type="agent")
def worker_b(topic: str) -> str:
    return llm(f"Research aspect B of: {topic}", max_tokens=96)


@trace(name="merge_agent_llm", span_type="agent")
def merge_agent(result_a: str | None, result_b: str) -> str:
    if result_a is None:
        raise ValueError("worker_a returned None — cannot merge")
    return llm(f"Merge these results:\nA: {result_a}\nB: {result_b}", max_tokens=128)


@trace(name="pipeline_scenario_c", span_type="agent")
def run_scenario_c():
    topic = "distributed tracing tools"
    a = worker_a(topic)
    b = worker_b(topic)
    merged = None
    try:
        merged = merge_agent(a, b)
    except Exception as e:
        console.print(f"  [dim]merge raised (expected): {e}[/dim]")
    return merged


run_scenario_c()
get_client().flush(timeout=8.0)
console.print("  [dim]flushed — waiting for ingestion...[/dim]")

tid_c = wait_for_trace("pipeline_scenario_c")
check("Scenario C trace ingested", tid_c is not None)

if tid_c:
    spans_c = {s["name"]: s for s in requests.get(f"{BASE_URL}/traces/{tid_c}").json().get("spans", [])}

    if "worker_a_llm" in spans_c and "merge_agent_llm" in spans_c:
        wa_id = spans_c["worker_a_llm"]["span_id"]
        merge_sources = spans_c["merge_agent_llm"].get("source_span_ids", [])
        check(
            "merge_agent.source_span_ids → worker_a",
            wa_id in merge_sources,
            f"merge source_span_ids={merge_sources}, worker_a_id={wa_id}",
        )

    blame_c = requests.get(f"{BASE_URL}/traces/{tid_c}/blame")
    if blame_c.ok:
        bc = blame_c.json()
        orig_c = [o["span_name"] for o in bc.get("originators", [])]
        fail_c = [f["span_name"] for f in bc.get("failure_points", [])]
        check("worker_a_llm is ORIGINATOR",  "worker_a_llm"   in orig_c, f"originators={orig_c}")
        check("merge_agent_llm is MANIFESTOR", "merge_agent_llm" in fail_c, f"failure_points={fail_c}")
        console.print(f"\n  [bold]Human summary:[/bold] {bc.get('human_summary', '')}")


# ══════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════

console.print()
console.rule("[bold white]Results")

table = Table(show_header=True, header_style="bold cyan", box=None)
table.add_column("Check", width=60)
table.add_column("Result", justify="center", width=8)
for c in check_log:
    table.add_row(c["label"], "[green]PASS[/green]" if c["passed"] else "[red]FAIL[/red]")
console.print(table)

total = checks_passed + checks_failed
console.print(
    f"\n  [bold]Total:[/bold] {total}   "
    f"[green]Passed:[/green] {checks_passed}   "
    f"[red]Failed:[/red] {checks_failed}   "
    f"[bold]{checks_passed/total*100:.0f}%[/bold] pass rate\n"
)
console.print("  [dim]Dashboard  → http://localhost:3000/traces[/dim]")
console.print(f"  [dim]Trace A    → http://localhost:3000/traces/{tid_a}[/dim]" if tid_a else "")
console.print(f"  [dim]Trace B    → http://localhost:3000/traces/{tid_b}[/dim]" if tid_b else "")
console.print(f"  [dim]Trace C    → http://localhost:3000/traces/{tid_c}[/dim]" if tid_c else "")

if checks_failed:
    sys.exit(1)
