#!/usr/bin/env python3
"""
Workspace isolation integration test for VerdictLens.

Verifies that workspace scoping is enforced at the backend level:
- Traces from workspace A are invisible to workspace B
- Datasets, evaluations, and prompts are workspace-scoped
- No cross-workspace data leakage

Usage:
    python examples/test_workspace_isolation.py
"""

import json
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

API = "http://localhost:8000"
WS_A = "test-ws-alpha"
WS_B = "test-ws-beta"

pass_count = 0
fail_count = 0


def header(ws: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-VerdictLens-Workspace": ws,
    }


def ok(label: str):
    global pass_count
    pass_count += 1
    print(f"  [PASS] {label}")


def fail(label: str, detail: str = ""):
    global fail_count
    fail_count += 1
    print(f"  [FAIL] {label} — {detail}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def send_trace(ws: str, trace_name: str) -> str:
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "trace_id": trace_id,
        "name": trace_name,
        "start_time": now,
        "end_time": now,
        "latency_ms": 100,
        "status": "error",
        "framework": "test",
        "model": "test-model",
        "input": {"query": f"test for {ws}"},
        "output": None,
        "error": {"type": "TestError", "message": f"error in {ws}"},
        "cost_usd": 0.001,
        "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "spans": [
            {
                "span_id": span_id,
                "parent_span_id": None,
                "name": f"{trace_name}_span",
                "span_type": "agent",
                "start_time": now,
                "end_time": now,
                "latency_ms": 50,
                "model": "test-model",
                "input": {"q": "test"},
                "output": None,
                "error": {"type": "TestError", "message": "span error"},
                "cost_usd": 0.0005,
                "token_usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                "metadata": {},
            }
        ],
        "metadata": {},
    }
    r = requests.post(f"{API}/traces", json=payload, headers=header(ws))
    assert r.status_code == 201, f"Trace ingest failed: {r.status_code} {r.text}"
    return trace_id


# =========================================================================
# STEP 1 — Trace isolation
# =========================================================================

section("STEP 1: Trace Isolation")

trace_a_id = send_trace(WS_A, "alpha_only_trace")
trace_b_id = send_trace(WS_B, "beta_only_trace")

time.sleep(2)

# WS_A should see only its trace
r = requests.get(f"{API}/traces", headers=header(WS_A))
traces_a = r.json()["traces"]
names_a = [t["name"] for t in traces_a]

if "alpha_only_trace" in names_a:
    ok("WS_A sees alpha_only_trace")
else:
    fail("WS_A sees alpha_only_trace", f"got: {names_a}")

if "beta_only_trace" not in names_a:
    ok("WS_A does NOT see beta_only_trace")
else:
    fail("WS_A does NOT see beta_only_trace", "LEAKAGE DETECTED")

# WS_B should see only its trace
r = requests.get(f"{API}/traces", headers=header(WS_B))
traces_b = r.json()["traces"]
names_b = [t["name"] for t in traces_b]

if "beta_only_trace" in names_b:
    ok("WS_B sees beta_only_trace")
else:
    fail("WS_B sees beta_only_trace", f"got: {names_b}")

if "alpha_only_trace" not in names_b:
    ok("WS_B does NOT see alpha_only_trace")
else:
    fail("WS_B does NOT see alpha_only_trace", "LEAKAGE DETECTED")


# =========================================================================
# STEP 2 — Trace detail isolation
# =========================================================================

section("STEP 2: Trace Detail Isolation")

# WS_A can fetch its own trace detail
r = requests.get(f"{API}/traces/{trace_a_id}", headers=header(WS_A))
if r.status_code == 200:
    ok("WS_A can fetch its own trace detail")
else:
    fail("WS_A can fetch its own trace detail", f"status={r.status_code}")

# WS_B cannot fetch WS_A's trace
r = requests.get(f"{API}/traces/{trace_a_id}", headers=header(WS_B))
if r.status_code == 404:
    ok("WS_B gets 404 for WS_A's trace (no leakage)")
else:
    fail("WS_B gets 404 for WS_A's trace", f"status={r.status_code} — LEAKAGE!")


# =========================================================================
# STEP 3 — Blame isolation
# =========================================================================

section("STEP 3: Blame Isolation")

r = requests.get(f"{API}/traces/{trace_a_id}/blame", headers=header(WS_A))
if r.status_code in (200, 422):
    ok("WS_A can run blame on its trace")
else:
    fail("WS_A can run blame on its trace", f"status={r.status_code}")

r = requests.get(f"{API}/traces/{trace_a_id}/blame", headers=header(WS_B))
if r.status_code == 404:
    ok("WS_B gets 404 for blame on WS_A's trace")
else:
    fail("WS_B gets 404 for blame on WS_A's trace", f"status={r.status_code} — LEAKAGE!")


# =========================================================================
# STEP 4 — Metrics isolation
# =========================================================================

section("STEP 4: Metrics Isolation")

r = requests.get(f"{API}/metrics?hours=24", headers=header(WS_A))
metrics_a = r.json()
r = requests.get(f"{API}/metrics?hours=24", headers=header(WS_B))
metrics_b = r.json()

if metrics_a["total_traces"] >= 1:
    ok(f"WS_A metrics: {metrics_a['total_traces']} traces")
else:
    fail("WS_A metrics show traces", f"got {metrics_a['total_traces']}")

if metrics_b["total_traces"] >= 1:
    ok(f"WS_B metrics: {metrics_b['total_traces']} traces")
else:
    fail("WS_B metrics show traces", f"got {metrics_b['total_traces']}")


# =========================================================================
# STEP 5 — Dataset isolation
# =========================================================================

section("STEP 5: Dataset Isolation")

r = requests.post(f"{API}/datasets", json={"name": "alpha_dataset"}, headers=header(WS_A))
if r.status_code == 201:
    dataset_a_id = r.json()["id"]
    ok("Created dataset in WS_A")
else:
    fail("Created dataset in WS_A", f"status={r.status_code}")
    dataset_a_id = None

r = requests.post(f"{API}/datasets", json={"name": "beta_dataset"}, headers=header(WS_B))
if r.status_code == 201:
    dataset_b_id = r.json()["id"]
    ok("Created dataset in WS_B")
else:
    fail("Created dataset in WS_B", f"status={r.status_code}")
    dataset_b_id = None

# List datasets for WS_A — should not see beta
r = requests.get(f"{API}/datasets", headers=header(WS_A))
ds_names_a = [d["name"] for d in r.json()]
if "alpha_dataset" in ds_names_a and "beta_dataset" not in ds_names_a:
    ok("WS_A datasets isolated correctly")
else:
    fail("WS_A datasets isolated", f"got: {ds_names_a}")

# List datasets for WS_B — should not see alpha
r = requests.get(f"{API}/datasets", headers=header(WS_B))
ds_names_b = [d["name"] for d in r.json()]
if "beta_dataset" in ds_names_b and "alpha_dataset" not in ds_names_b:
    ok("WS_B datasets isolated correctly")
else:
    fail("WS_B datasets isolated", f"got: {ds_names_b}")

# WS_B should NOT be able to fetch WS_A's dataset
if dataset_a_id:
    r = requests.get(f"{API}/datasets/{dataset_a_id}", headers=header(WS_B))
    if r.status_code == 404:
        ok("WS_B gets 404 for WS_A's dataset (no leakage)")
    else:
        fail("WS_B gets 404 for WS_A's dataset", f"status={r.status_code} — LEAKAGE!")


# =========================================================================
# STEP 6 — Evaluation isolation
# =========================================================================

section("STEP 6: Evaluation Isolation")

# Add an example to each dataset so we can run evaluations
if dataset_a_id:
    requests.post(
        f"{API}/datasets/{dataset_a_id}/examples",
        json={"inputs": {"q": "test"}, "outputs": {"a": "42"}, "expected": {"a": "42"}},
        headers=header(WS_A),
    )
if dataset_b_id:
    requests.post(
        f"{API}/datasets/{dataset_b_id}/examples",
        json={"inputs": {"q": "test"}, "outputs": {"a": "99"}, "expected": {"a": "99"}},
        headers=header(WS_B),
    )

# Create evaluation in WS_A
eval_a_id = None
if dataset_a_id:
    r = requests.post(
        f"{API}/evaluations",
        json={
            "name": "alpha_eval",
            "dataset_id": dataset_a_id,
            "scorers": [{"type": "exact_match"}],
            "mode": "replay",
        },
        headers=header(WS_A),
    )
    if r.status_code == 201:
        eval_a_id = r.json()["id"]
        ok("Created evaluation in WS_A")
    else:
        fail("Created evaluation in WS_A", f"status={r.status_code} {r.text[:200]}")

# List evaluations — WS_B should not see WS_A's
r = requests.get(f"{API}/evaluations", headers=header(WS_B))
eval_names_b = [e["name"] for e in r.json()]
if "alpha_eval" not in eval_names_b:
    ok("WS_B evaluation list does not contain alpha_eval")
else:
    fail("WS_B evaluation list isolation", f"got: {eval_names_b} — LEAKAGE!")

# WS_B should get 404 for WS_A's eval results
if eval_a_id:
    r = requests.get(f"{API}/evaluations/{eval_a_id}/results", headers=header(WS_B))
    results = r.json()
    if isinstance(results, list) and len(results) == 0:
        ok("WS_B gets empty results for WS_A's evaluation")
    else:
        fail("WS_B eval results isolation", f"got {len(results) if isinstance(results, list) else 'error'} results — LEAKAGE!")


# =========================================================================
# STEP 7 — Prompt / Playground isolation
# =========================================================================

section("STEP 7: Prompt Isolation")

r = requests.post(
    f"{API}/playground/prompts",
    json={"name": "alpha_prompt", "content": "Hello from alpha"},
    headers=header(WS_A),
)
if r.status_code == 201:
    prompt_a_id = r.json()["id"]
    ok("Saved prompt in WS_A")
else:
    fail("Saved prompt in WS_A", f"status={r.status_code}")
    prompt_a_id = None

r = requests.get(f"{API}/playground/prompts", headers=header(WS_B))
prompt_names_b = [p["name"] for p in r.json()]
if "alpha_prompt" not in prompt_names_b:
    ok("WS_B prompt list does not contain alpha_prompt")
else:
    fail("WS_B prompt list isolation", f"got: {prompt_names_b} — LEAKAGE!")

if prompt_a_id:
    r = requests.get(f"{API}/playground/prompts/{prompt_a_id}", headers=header(WS_B))
    if r.status_code == 404:
        ok("WS_B gets 404 for WS_A's prompt version")
    else:
        fail("WS_B prompt version isolation", f"status={r.status_code} — LEAKAGE!")


# =========================================================================
# STEP 8 — Replay isolation
# =========================================================================

section("STEP 8: Replay Isolation")

r = requests.get(f"{API}/traces/{trace_a_id}/replays", headers=header(WS_A))
if r.status_code == 200:
    ok("WS_A can list replays for its trace")
else:
    fail("WS_A can list replays for its trace", f"status={r.status_code}")

r = requests.get(f"{API}/traces/{trace_a_id}/replays", headers=header(WS_B))
if r.status_code == 200 and len(r.json()) == 0:
    ok("WS_B gets empty replays for WS_A's trace")
elif r.status_code == 404:
    ok("WS_B gets 404 for replays on WS_A's trace")
else:
    fail("WS_B replay isolation", f"status={r.status_code}, body={r.text[:200]}")


# =========================================================================
# SUMMARY
# =========================================================================

section("TEST SUMMARY")
total = pass_count + fail_count
print(f"\n  Total: {total}  |  Passed: {pass_count}  |  Failed: {fail_count}")

if fail_count > 0:
    print("\n  WORKSPACE ISOLATION INCOMPLETE — see failures above")
    sys.exit(1)
else:
    print("\n  ALL TESTS PASSED — workspace isolation is enforced")
    sys.exit(0)
