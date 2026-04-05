"""
VerdictLens Multi-Agent Blame Demo.

A 3-agent pipeline where one agent intentionally passes malformed data,
causing a downstream cascade failure.  After running, the demo calls the
blame endpoint to identify the root cause.

Pipeline:
    ResearchAgent → SummaryAgent → WriterAgent

ResearchAgent intentionally returns data with a null "findings" field,
causing SummaryAgent to receive invalid input, which propagates an error
to WriterAgent.  Blame analysis should identify ResearchAgent as the
root cause.

Usage:
    cd verdictlens
    source .venv/bin/activate
    python examples/multi_agent_demo.py

Requires: the VerdictLens backend running at localhost:8000.
"""

from __future__ import annotations

import json
import time
import traceback
from uuid import uuid4

import httpx

from verdictlens import configure, get_client
from verdictlens.types import SpanRecord, TokenUsage, TraceEvent

configure(base_url="http://localhost:8000")


def _now_iso() -> str:
    """Current UTC ISO timestamp."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_pipeline(topic: str) -> None:
    """
    Execute the 3-agent pipeline as a single trace with parent-child spans,
    then send it to the backend so the blame engine can walk the full chain.

    :param topic: Research topic.
    :returns: None
    """
    trace_id = str(uuid4())
    root_span_id = str(uuid4())
    research_span_id = str(uuid4())
    summary_span_id = str(uuid4())
    writer_span_id = str(uuid4())

    trace_start = _now_iso()
    t0 = time.perf_counter()
    spans: list[SpanRecord] = []

    # ── Root orchestrator span ──────────────────────────────────
    spans.append(SpanRecord(
        span_id=root_span_id,
        parent_span_id=None,
        name="PipelineOrchestrator",
        span_type="agent",
        start_time=trace_start,
        model=None,
        decision="Orchestrate Research → Summary → Writer pipeline",
        confidence_score=0.9,
        input={"topic": topic},
        metadata={"span_role": "root"},
    ))

    # ── Step 1: ResearchAgent ───────────────────────────────────
    print(f"\n  [1/3] ResearchAgent — fetching data for: {topic}")
    r_start = _now_iso()
    r_t0 = time.perf_counter()
    time.sleep(0.2)

    research_output = {
        "topic": topic,
        "findings": None,
        "sources": ["arxiv", "google_scholar"],
    }
    r_t1 = time.perf_counter()
    r_end = _now_iso()

    print(f"         Output: findings={research_output.get('findings')}")
    print(f"         Confidence: 0.3")

    spans.append(SpanRecord(
        span_id=research_span_id,
        parent_span_id=root_span_id,
        name="ResearchAgent",
        span_type="agent",
        start_time=r_start,
        end_time=r_end,
        latency_ms=round((r_t1 - r_t0) * 1000, 3),
        model="gpt-4o",
        input={"topic": topic},
        output=research_output,
        decision="Returned null findings due to simulated API failure",
        confidence_score=0.3,
        token_usage=TokenUsage(prompt_tokens=500, completion_tokens=200, total_tokens=700),
        cost_usd=0.0115,
        error=None,
    ))

    # ── Step 2: SummaryAgent ────────────────────────────────────
    print(f"\n  [2/3] SummaryAgent — summarizing findings...")
    s_start = _now_iso()
    s_t0 = time.perf_counter()
    time.sleep(0.15)

    summary_error = None
    summary_output = None
    findings = research_output.get("findings")
    if not findings:
        summary_error = {
            "type": "ValueError",
            "message": "Cannot summarize: 'findings' field is null or empty. ResearchAgent returned malformed data.",
            "stack": "".join(traceback.format_stack()),
        }
        print(f"         FAILED: {summary_error['message']}")
    else:
        summary_output = {"summary": f"Summary of {len(findings)} findings"}

    s_t1 = time.perf_counter()
    s_end = _now_iso()

    spans.append(SpanRecord(
        span_id=summary_span_id,
        parent_span_id=research_span_id,
        name="SummaryAgent",
        span_type="agent",
        start_time=s_start,
        end_time=s_end,
        latency_ms=round((s_t1 - s_t0) * 1000, 3),
        model="gpt-4o-mini",
        input=research_output,
        output=summary_output,
        decision="Summarize research findings",
        confidence_score=0.8,
        token_usage=TokenUsage(prompt_tokens=300, completion_tokens=100, total_tokens=400),
        cost_usd=0.0003,
        error=summary_error,
    ))

    # ── Step 3: WriterAgent ─────────────────────────────────────
    if summary_error:
        print(f"\n  [3/3] WriterAgent — skipped (upstream failure)")
    else:
        print(f"\n  [3/3] WriterAgent — writing report...")
        w_start = _now_iso()
        w_t0 = time.perf_counter()
        time.sleep(0.1)
        w_t1 = time.perf_counter()
        w_end = _now_iso()
        spans.append(SpanRecord(
            span_id=writer_span_id,
            parent_span_id=summary_span_id,
            name="WriterAgent",
            span_type="agent",
            start_time=w_start,
            end_time=w_end,
            latency_ms=round((w_t1 - w_t0) * 1000, 3),
            model="gpt-4o",
            input=summary_output,
            output={"report": "Final report"},
            decision="Write final report from summary",
            confidence_score=0.9,
            cost_usd=0.0195,
        ))

    # ── Finalize root span and trace ────────────────────────────
    t1 = time.perf_counter()
    trace_end = _now_iso()
    total_ms = round((t1 - t0) * 1000, 3)
    has_error = summary_error is not None

    spans[0].end_time = trace_end
    spans[0].latency_ms = total_ms
    spans[0].output = {"pipeline_status": "error" if has_error else "complete", "topic": topic}
    trace = TraceEvent(
        trace_id=trace_id,
        name="MultiAgentPipeline",
        start_time=trace_start,
        end_time=trace_end,
        latency_ms=total_ms,
        status="error" if has_error else "success",
        framework="custom",
        model="gpt-4o",
        input={"topic": topic},
        output=None if has_error else {"report": "Final report"},
        error=summary_error,
        spans=spans,
    )

    print(f"\n  Sending trace ({len(spans)} spans) to backend...")
    payload = trace.model_dump(mode="json")
    get_client().send_trace(payload)
    get_client().flush(timeout=5.0)
    time.sleep(2.0)

    return trace_id


def fetch_blame(trace_id: str) -> None:
    """
    Call the blame endpoint and print results.

    :param trace_id: Trace identifier to analyze.
    :returns: None
    """
    print("\n  Fetching blame analysis from backend...")

    try:
        blame_resp = httpx.get(f"http://localhost:8000/traces/{trace_id}/blame")

        if blame_resp.status_code == 422:
            print(f"  Trace has no error spans — blame not applicable.")
            return
        if blame_resp.status_code == 404:
            print(f"  Trace not found yet. Try again in a moment.")
            return
        if blame_resp.status_code != 200:
            print(f"  Blame API returned {blame_resp.status_code}: {blame_resp.text[:200]}")
            return

        blame = blame_resp.json()
        rc = blame["root_cause"]

        print(f"\n  {'=' * 56}")
        print(f"  BLAME ANALYSIS RESULT")
        print(f"  {'=' * 56}")
        print(f"  Root Cause Agent: {rc['agent_name']}")
        print(f"  Blame Score:      {rc['blame_score']:.0%}")
        print(f"  Reason:           {rc['reason']}")
        if rc.get("decision"):
            print(f"  Decision:         {rc['decision']}")
        print(f"\n  Failure Cascade:")
        for i, step in enumerate(blame["cascade"], 1):
            print(f"    {i}. {step}")
        print(f"\n  Chain Length:     {len(blame['full_chain'])} spans")
        print(f"  {'=' * 56}")

    except httpx.ConnectError:
        print("  Cannot connect to backend at localhost:8000. Is it running?")
    except Exception as e:
        print(f"  Blame fetch error: {e}")


def main() -> None:
    """Run the full demo."""
    print("=" * 60)
    print("  VerdictLens — Multi-Agent Blame Demo")
    print("  Pipeline: ResearchAgent → SummaryAgent → WriterAgent")
    print("=" * 60)

    trace_id = run_pipeline("Transformer architectures in multi-agent systems 2026")

    fetch_blame(trace_id)

    print(f"\n  Dashboard: http://localhost:3000/traces")
    print(f"  (Click the error trace → 'Blame Analysis' tab)")
    print("=" * 60)


if __name__ == "__main__":
    main()
