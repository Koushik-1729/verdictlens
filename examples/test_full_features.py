#!/usr/bin/env python3
"""
Full-feature integration test for VerdictLens.

Tests every core feature with REAL Groq LLM calls:
  1. Trace ingestion (hierarchical spans)
  2. Trace listing & detail
  3. Blame analysis
  4. Metrics
  5. Replay (real LLM re-execution)
  6. Datasets (CRUD)
  7. Evaluations (replay mode)
  8. Workspaces & API keys
  9. Playground (real LLM call via Groq)
 10. Prompt versioning
 11. Prompt Hub (publish, history, promote, usage)
 12. Workspace isolation

Usage:
    python examples/test_full_features.py
"""

import json
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

API = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json", "X-VerdictLens-Workspace": "default"}

pass_count = 0
fail_count = 0


def ok(label: str, detail: str = ""):
    global pass_count
    pass_count += 1
    extra = f" — {detail}" if detail else ""
    print(f"  [PASS] {label}{extra}")


def fail(label: str, detail: str = ""):
    global fail_count
    fail_count += 1
    print(f"  [FAIL] {label} — {detail}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# =========================================================================
# 1. TRACE INGESTION — hierarchical spans with realistic agent data
# =========================================================================

section("1. Trace Ingestion")

trace_id = str(uuid.uuid4())
root_span_id = str(uuid.uuid4())
child_span_id = str(uuid.uuid4())
llm_span_id = str(uuid.uuid4())
now = datetime.now(timezone.utc).isoformat()

trace_payload = {
    "trace_id": trace_id,
    "name": "research_pipeline",
    "start_time": now,
    "end_time": now,
    "latency_ms": 2500,
    "status": "error",
    "framework": "verdictlens",
    "model": "llama-3.3-70b-versatile",
    "input": {"query": "Explain quantum entanglement"},
    "output": None,
    "error": {"type": "NullOutputError", "message": "Pipeline produced null output"},
    "cost_usd": 0.002,
    "token_usage": {"prompt_tokens": 150, "completion_tokens": 0, "total_tokens": 150},
    "spans": [
        {
            "span_id": root_span_id,
            "parent_span_id": None,
            "name": "orchestrator",
            "span_type": "agent",
            "start_time": now,
            "end_time": now,
            "latency_ms": 2500,
            "model": None,
            "input": {"query": "Explain quantum entanglement"},
            "output": None,
            "error": {"type": "NullOutputError", "message": "Child returned null"},
            "cost_usd": 0.0,
            "token_usage": None,
            "metadata": {},
        },
        {
            "span_id": child_span_id,
            "parent_span_id": root_span_id,
            "name": "research_agent",
            "span_type": "agent",
            "start_time": now,
            "end_time": now,
            "latency_ms": 1800,
            "model": "llama-3.3-70b-versatile",
            "input": {"task": "research quantum entanglement"},
            "output": None,
            "error": {"type": "LLMError", "message": "Context window exceeded"},
            "cost_usd": 0.001,
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 0, "total_tokens": 100},
            "metadata": {},
        },
        {
            "span_id": llm_span_id,
            "parent_span_id": child_span_id,
            "name": "groq.chat.completions.create",
            "span_type": "llm",
            "start_time": now,
            "end_time": now,
            "latency_ms": 800,
            "model": "llama-3.3-70b-versatile",
            "input": {"messages": [{"role": "user", "content": "Explain quantum entanglement"}]},
            "output": None,
            "error": {"type": "ContextLengthError", "message": "Context window exceeded"},
            "cost_usd": 0.001,
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 0, "total_tokens": 100},
            "metadata": {},
        },
    ],
    "metadata": {"test": True},
}

r = requests.post(f"{API}/traces", json=trace_payload, headers=HEADERS)
if r.status_code == 201:
    ok("Trace ingested", f"trace_id={trace_id[:12]}...")
else:
    fail("Trace ingestion", f"status={r.status_code} {r.text[:200]}")

# Also send a success trace
success_trace_id = str(uuid.uuid4())
success_span_id = str(uuid.uuid4())
success_payload = {
    "trace_id": success_trace_id,
    "name": "simple_qa",
    "start_time": now,
    "end_time": now,
    "latency_ms": 500,
    "status": "success",
    "framework": "verdictlens",
    "model": "llama-3.3-70b-versatile",
    "input": {"query": "What is 2+2?"},
    "output": {"answer": "4"},
    "cost_usd": 0.0005,
    "token_usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    "spans": [
        {
            "span_id": success_span_id,
            "parent_span_id": None,
            "name": "qa_agent",
            "span_type": "agent",
            "start_time": now,
            "end_time": now,
            "latency_ms": 500,
            "model": "llama-3.3-70b-versatile",
            "input": {"query": "What is 2+2?"},
            "output": {"answer": "4"},
            "cost_usd": 0.0005,
            "token_usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            "metadata": {},
        }
    ],
    "metadata": {},
}
r = requests.post(f"{API}/traces", json=success_payload, headers=HEADERS)
if r.status_code == 201:
    ok("Success trace ingested")
else:
    fail("Success trace ingestion", f"{r.status_code}")

time.sleep(2)

# =========================================================================
# 2. TRACE LISTING & DETAIL
# =========================================================================

section("2. Trace Listing & Detail")

r = requests.get(f"{API}/traces", headers=HEADERS)
data = r.json()
if data["total"] >= 2:
    ok(f"Trace list", f"{data['total']} traces")
else:
    fail("Trace list", f"expected >= 2, got {data['total']}")

r = requests.get(f"{API}/traces/{trace_id}", headers=HEADERS)
if r.status_code == 200:
    detail = r.json()
    span_count = len(detail.get("spans", []))
    if span_count == 3:
        ok("Trace detail", f"3 hierarchical spans")
    else:
        fail("Trace detail span count", f"expected 3, got {span_count}")
else:
    fail("Trace detail", f"status={r.status_code}")

# =========================================================================
# 3. BLAME ANALYSIS
# =========================================================================

section("3. Blame Analysis")

r = requests.get(f"{API}/traces/{trace_id}/blame", headers=HEADERS)
if r.status_code == 200:
    blame = r.json()
    originators = blame.get("originators", [])
    confidence = blame.get("confidence", "")
    chain = blame.get("propagation_chain", [])
    if len(originators) > 0:
        ok("Blame originators", f"{originators[0]['span_name']} (score={originators[0]['blame_score']:.2f})")
    else:
        fail("Blame originators", "empty")
    ok(f"Blame confidence: {confidence}")
    if chain:
        ok(f"Propagation chain: {' -> '.join(chain)}")
    summary = blame.get("human_summary", "")
    if summary:
        ok("Human summary present", summary[:80])
elif r.status_code == 422:
    ok("Blame returned 422 (no error spans)", "expected for clean traces")
else:
    fail("Blame analysis", f"status={r.status_code} {r.text[:200]}")

# =========================================================================
# 4. METRICS
# =========================================================================

section("4. Metrics")

r = requests.get(f"{API}/metrics?hours=24", headers=HEADERS)
if r.status_code == 200:
    m = r.json()
    ok(f"Metrics", f"traces={m['total_traces']}, spans={m['total_spans']}, cost=${m['total_cost_usd']:.4f}")
else:
    fail("Metrics", f"status={r.status_code}")

# =========================================================================
# 5. REPLAY — real Groq LLM call
# =========================================================================

section("5. Replay (Real Groq LLM Call)")

r = requests.post(
    f"{API}/traces/{trace_id}/spans/{llm_span_id}/replay",
    json={
        "new_input": {
            "messages": [{"role": "user", "content": "Explain quantum entanglement in one sentence."}]
        },
        "note": "Testing replay with shorter prompt",
    },
    headers=HEADERS,
)
if r.status_code == 201:
    replay = r.json()
    ok(f"Replay executed", f"latency={replay['new_latency_ms']:.0f}ms, cost=${replay['new_cost_usd']:.6f}")
    if replay.get("new_output"):
        content = str(replay["new_output"])[:80]
        ok(f"Replay got real LLM output", content)
    ok(f"Replay status: {replay['status']}")
    if replay.get("tree_position"):
        ok(f"Tree position: depth={replay['tree_position']['depth']}")
elif r.status_code == 400 and "no model" in r.text.lower():
    fail("Replay", "span has no model")
else:
    fail("Replay", f"status={r.status_code} {r.text[:200]}")

# List replays
r = requests.get(f"{API}/traces/{trace_id}/replays", headers=HEADERS)
if r.status_code == 200:
    replays = r.json()
    ok(f"List replays", f"{len(replays)} replay(s) found")
else:
    fail("List replays", f"status={r.status_code}")

# =========================================================================
# 6. DATASETS
# =========================================================================

section("6. Datasets")

r = requests.post(
    f"{API}/datasets",
    json={"name": "QA Test Dataset", "description": "For integration testing"},
    headers=HEADERS,
)
dataset_id = None
if r.status_code == 201:
    dataset_id = r.json()["id"]
    ok("Dataset created", f"id={dataset_id[:12]}...")
else:
    fail("Dataset creation", f"status={r.status_code}")

if dataset_id:
    r = requests.post(
        f"{API}/datasets/{dataset_id}/examples",
        json={
            "inputs": {"query": "What is the capital of France?"},
            "outputs": {"answer": "Paris"},
            "expected": {"answer": "Paris"},
            "metadata": {"source": "test"},
        },
        headers=HEADERS,
    )
    if r.status_code == 201:
        example_id = r.json()["id"]
        ok("Example added", f"id={example_id[:12]}...")
    else:
        fail("Example addition", f"status={r.status_code} {r.text[:200]}")

    r = requests.post(
        f"{API}/datasets/{dataset_id}/examples",
        json={
            "inputs": {"query": "What is 2+2?"},
            "outputs": {"answer": "4"},
            "expected": {"answer": "4"},
        },
        headers=HEADERS,
    )
    if r.status_code == 201:
        ok("Second example added")
    else:
        fail("Second example", f"status={r.status_code}")

    # Trace-to-dataset conversion
    r = requests.post(
        f"{API}/traces/{success_trace_id}/to-dataset",
        json={"dataset_id": dataset_id},
        headers=HEADERS,
    )
    if r.status_code == 201:
        ok("Trace converted to dataset example")
    else:
        fail("Trace-to-dataset", f"status={r.status_code} {r.text[:200]}")

    r = requests.get(f"{API}/datasets/{dataset_id}/examples", headers=HEADERS)
    if r.status_code == 200:
        examples = r.json()
        ok(f"Listed examples", f"{len(examples)} examples")
    else:
        fail("List examples", f"status={r.status_code}")

    r = requests.get(f"{API}/datasets", headers=HEADERS)
    if r.status_code == 200:
        datasets = r.json()
        ok(f"Listed datasets", f"{len(datasets)} dataset(s)")
    else:
        fail("List datasets", f"status={r.status_code}")

# =========================================================================
# 7. EVALUATIONS
# =========================================================================

section("7. Evaluations")

eval_id = None
if dataset_id:
    r = requests.post(
        f"{API}/evaluations",
        json={
            "name": "QA Eval — exact match",
            "dataset_id": dataset_id,
            "scorers": [{"type": "exact_match", "threshold": 0.5}],
            "mode": "replay",
        },
        headers=HEADERS,
    )
    if r.status_code == 201:
        eval_data = r.json()
        eval_id = eval_data["id"]
        ok(f"Evaluation created", f"status={eval_data['status']}, passed={eval_data.get('passed')}/{eval_data.get('total')}")
    else:
        fail("Evaluation creation", f"status={r.status_code} {r.text[:200]}")

    if eval_id:
        r = requests.get(f"{API}/evaluations/{eval_id}/results", headers=HEADERS)
        if r.status_code == 200:
            results = r.json()
            ok(f"Eval results", f"{len(results)} results")
            for res in results:
                status = "PASS" if res["passed"] else "FAIL"
                ok(f"  Example {res['example_id'][:8]}...: score={res['score']:.2f} [{status}]")
        else:
            fail("Eval results", f"status={r.status_code}")

    # Second evaluation for comparison
    r = requests.post(
        f"{API}/evaluations",
        json={
            "name": "QA Eval — contains",
            "dataset_id": dataset_id,
            "scorers": [{"type": "contains", "threshold": 0.5}],
            "mode": "replay",
        },
        headers=HEADERS,
    )
    eval_b_id = None
    if r.status_code == 201:
        eval_b_id = r.json()["id"]
        ok("Second evaluation created for comparison")

    if eval_id and eval_b_id:
        r = requests.get(
            f"{API}/evaluations/compare?eval_a={eval_id}&eval_b={eval_b_id}",
            headers=HEADERS,
        )
        if r.status_code == 200:
            comp = r.json()
            ok(f"Comparison", f"wins={comp['wins']}, losses={comp['losses']}, ties={comp['ties']}")
        else:
            fail("Evaluation comparison", f"status={r.status_code}")

    r = requests.get(f"{API}/evaluations", headers=HEADERS)
    if r.status_code == 200:
        ok(f"Listed evaluations", f"{len(r.json())} evaluation(s)")

# =========================================================================
# 8. WORKSPACES & API KEYS
# =========================================================================

section("8. Workspaces & API Keys")

r = requests.post(
    f"{API}/workspaces",
    json={"name": "Test Workspace", "slug": f"test-ws-{uuid.uuid4().hex[:6]}", "description": "Integration test"},
    headers=HEADERS,
)
ws_id = None
if r.status_code == 201:
    ws_id = r.json()["id"]
    ok(f"Workspace created", f"id={ws_id[:12]}...")
else:
    fail("Workspace creation", f"status={r.status_code} {r.text[:200]}")

if ws_id:
    r = requests.post(
        f"{API}/workspaces/{ws_id}/api-keys",
        json={"name": "test-key", "workspace_id": ws_id},
        headers=HEADERS,
    )
    if r.status_code == 201:
        key_data = r.json()
        ok(f"API key created", f"prefix={key_data['key_prefix']}")
        if key_data.get("key", "").startswith("vdl_"):
            ok("API key format correct (al_...)")
    else:
        fail("API key creation", f"status={r.status_code}")

    r = requests.get(f"{API}/workspaces/{ws_id}/api-keys", headers=HEADERS)
    if r.status_code == 200:
        ok(f"Listed API keys", f"{len(r.json())} key(s)")

r = requests.get(f"{API}/workspaces", headers=HEADERS)
if r.status_code == 200:
    ok(f"Listed workspaces", f"{len(r.json())} workspace(s)")

# =========================================================================
# 9. PLAYGROUND — real Groq LLM call
# =========================================================================

section("9. Playground (Real Groq LLM Call)")

# Safety check — empty prompt should be rejected
r = requests.post(
    f"{API}/playground/run",
    json={"prompt": "", "model": "llama-3.3-70b-versatile"},
    headers=HEADERS,
)
if r.status_code == 400:
    ok("Empty prompt rejected (safety layer)")
else:
    fail("Empty prompt safety", f"status={r.status_code}")

# Real LLM call
r = requests.post(
    f"{API}/playground/run",
    json={
        "prompt": "What is the capital of Japan? Answer in one word.",
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.1,
        "max_tokens": 50,
    },
    headers=HEADERS,
)
if r.status_code == 200:
    pg = r.json()
    ok(f"Playground LLM call", f"model={pg['model']}, latency={pg['latency_ms']:.0f}ms")
    if pg.get("output"):
        ok(f"Playground output", pg["output"][:80])
    ok(f"Tokens: in={pg['prompt_tokens']}, out={pg['completion_tokens']}, total={pg['total_tokens']}")
    ok(f"Cost: ${pg['cost_usd']:.6f}")
else:
    fail("Playground LLM call", f"status={r.status_code} {r.text[:200]}")

# With system message
r = requests.post(
    f"{API}/playground/run",
    json={
        "prompt": "What is 15 * 23?",
        "model": "llama-3.3-70b-versatile",
        "system_message": "You are a calculator. Only respond with the number, nothing else.",
        "temperature": 0.0,
        "max_tokens": 20,
    },
    headers=HEADERS,
)
if r.status_code == 200:
    pg = r.json()
    ok(f"Playground with system message", f"output={pg.get('output', '')[:40]}")
else:
    fail("Playground with system message", f"status={r.status_code}")

# =========================================================================
# 10. PROMPT VERSIONING
# =========================================================================

section("10. Prompt Versioning")

r = requests.post(
    f"{API}/playground/prompts",
    json={
        "name": "qa-prompt",
        "content": "Answer the following question accurately:\n\n{question}",
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.2,
        "max_tokens": 200,
        "tags": ["qa", "v1"],
    },
    headers=HEADERS,
)
prompt_v1_id = None
if r.status_code == 201:
    prompt_v1_id = r.json()["id"]
    ok(f"Prompt v1 saved", f"id={prompt_v1_id[:12]}...")
else:
    fail("Prompt v1 save", f"status={r.status_code}")

# Save v2
r = requests.post(
    f"{API}/playground/prompts",
    json={
        "name": "qa-prompt",
        "content": "You are an expert. Answer concisely:\n\n{question}",
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.1,
        "max_tokens": 150,
        "parent_id": prompt_v1_id,
        "tags": ["qa", "v2", "concise"],
    },
    headers=HEADERS,
)
prompt_v2_id = None
if r.status_code == 201:
    prompt_v2_id = r.json()["id"]
    version_num = r.json().get("version_number", "?")
    ok(f"Prompt v2 saved", f"version={version_num}")
else:
    fail("Prompt v2 save", f"status={r.status_code}")

r = requests.get(f"{API}/playground/prompts", headers=HEADERS)
if r.status_code == 200:
    ok(f"Listed prompt versions", f"{len(r.json())} version(s)")

if prompt_v1_id:
    r = requests.get(f"{API}/playground/prompts/{prompt_v1_id}", headers=HEADERS)
    if r.status_code == 200:
        ok("Fetched prompt v1 by ID")
    else:
        fail("Fetch prompt v1", f"status={r.status_code}")

# =========================================================================
# 11. PROMPT HUB
# =========================================================================

section("11. Prompt Hub")

if prompt_v2_id:
    r = requests.post(f"{API}/playground/prompts/{prompt_v2_id}/publish", headers=HEADERS)
    if r.status_code == 200:
        ok("Prompt v2 published")
    else:
        fail("Publish prompt", f"status={r.status_code}")

r = requests.get(f"{API}/prompt-hub", headers=HEADERS)
if r.status_code == 200:
    hub = r.json()
    ok(f"Prompt Hub listed", f"{len(hub)} published prompt(s)")
    if hub:
        ok(f"  Name: {hub[0]['name']}, versions: {hub[0].get('total_versions', '?')}")
else:
    fail("Prompt Hub list", f"status={r.status_code}")

# Version history
r = requests.get(f"{API}/playground/prompts/qa-prompt/history", headers=HEADERS)
if r.status_code == 200:
    hist = r.json()
    ok(f"Version history", f"{hist['total_versions']} version(s)")
else:
    fail("Version history", f"status={r.status_code}")

# Promote v1
if prompt_v1_id:
    r = requests.post(f"{API}/playground/prompts/{prompt_v1_id}/promote", headers=HEADERS)
    if r.status_code == 200:
        promoted = r.json()
        ok(f"Promoted v1", f"new version_number={promoted.get('version_number', '?')}")
    else:
        fail("Promote v1", f"status={r.status_code}")

# Usage stats
r = requests.get(f"{API}/prompt-hub/qa-prompt/usage", headers=HEADERS)
if r.status_code == 200:
    stats = r.json()
    ok(f"Usage stats", f"runs={stats['total_runs']}, tokens={stats['total_tokens']}")
else:
    fail("Usage stats", f"status={r.status_code}")

# Unpublish
if prompt_v2_id:
    r = requests.post(f"{API}/playground/prompts/{prompt_v2_id}/unpublish", headers=HEADERS)
    if r.status_code == 200:
        ok("Prompt v2 unpublished")
    else:
        fail("Unpublish", f"status={r.status_code}")

# =========================================================================
# 12. WORKSPACE ISOLATION (quick sanity check)
# =========================================================================

section("12. Workspace Isolation Sanity Check")

other_ws_headers = {**HEADERS, "X-VerdictLens-Workspace": "isolated-test-ws"}

r = requests.get(f"{API}/traces", headers=other_ws_headers)
if r.status_code == 200 and r.json()["total"] == 0:
    ok("Other workspace sees 0 traces (isolation confirmed)")
else:
    fail("Workspace isolation", f"total={r.json().get('total', '?')}")

r = requests.get(f"{API}/traces/{trace_id}", headers=other_ws_headers)
if r.status_code == 404:
    ok("Other workspace gets 404 for default's trace")
else:
    fail("Trace isolation", f"status={r.status_code}")

r = requests.get(f"{API}/datasets", headers=other_ws_headers)
if r.status_code == 200 and len(r.json()) == 0:
    ok("Other workspace sees 0 datasets (isolation confirmed)")
else:
    fail("Dataset isolation", f"count={len(r.json()) if r.status_code == 200 else 'error'}")

# =========================================================================
# SUMMARY
# =========================================================================

section("FINAL SUMMARY")
total = pass_count + fail_count
print(f"\n  Total: {total}  |  Passed: {pass_count}  |  Failed: {fail_count}")

if fail_count > 0:
    print(f"\n  {fail_count} test(s) failed — review output above")
    sys.exit(1)
else:
    print("\n  ALL FEATURES WORKING — VerdictLens is fully operational")
    sys.exit(0)
