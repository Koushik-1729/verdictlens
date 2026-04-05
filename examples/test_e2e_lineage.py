"""
End-to-end integration test for Option B data-flow lineage.

No LLM required — uses @trace decorators to create real spans with
source_span_ids, sends them to the running backend, then validates
that the blame API returns the correct originator/manifestor roles.

Usage:
    pip install -e ./sdk requests
    python examples/test_e2e_lineage.py

Requires:
    docker compose up -d (backend + clickhouse running on port 8000)
"""

import sys
import time
import requests

# ── SDK setup ────────────────────────────────────────────────────

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "sdk"))

from verdictlens import configure, trace
from verdictlens.client import get_client

BASE_URL = "http://localhost:8000"
configure(base_url=BASE_URL, disabled=False, reset_client=True)

PASS  = "\033[32m✓\033[0m"
FAIL  = "\033[31m✗\033[0m"
INFO  = "\033[34m·\033[0m"

failures = []

def check(label, cond, detail=""):
    if cond:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}" + (f"  →  {detail}" if detail else ""))
        failures.append(label)


# ════════════════════════════════════════════════════════════════
# Scenario 1: Linear chain  producer → consumer (consumer errors)
#   Expected: producer = ORIGINATOR, consumer = MANIFESTOR
# ════════════════════════════════════════════════════════════════

print("\n[Scenario 1] Linear chain — producer null → consumer fails")

trace_id_1 = None

@trace(name="producer_agent", span_type="agent")
def producer_bad() -> dict:
    return None  # bad: null output

@trace(name="consumer_agent", span_type="agent")
def consumer_receives(data):
    if data is None:
        raise ValueError("received null from producer")
    return {"result": data}

@trace(name="pipeline_linear", span_type="agent")
def pipeline_linear():
    result = producer_bad()
    try:
        return consumer_receives(result)
    except Exception:
        return None

pipeline_linear()
get_client().flush(timeout=5.0)
print(f"  {INFO} trace flushed, waiting for ingestion...")
time.sleep(2)

# Find the trace
resp = requests.get(f"{BASE_URL}/traces", params={"name": "pipeline_linear", "page_size": 5})
check("GET /traces returns 200", resp.status_code == 200, resp.text[:200])

traces = resp.json().get("traces", [])
check("trace ingested", len(traces) >= 1, f"got {len(traces)} traces")

if traces:
    trace_id_1 = traces[0]["trace_id"]
    print(f"  {INFO} trace_id = {trace_id_1}")

    # Get trace detail to inspect spans
    detail = requests.get(f"{BASE_URL}/traces/{trace_id_1}").json()
    spans = detail.get("spans", [])
    span_by_name = {s["name"]: s for s in spans}

    check("producer_agent span exists", "producer_agent" in span_by_name)
    check("consumer_agent span exists", "consumer_agent" in span_by_name)

    if "producer_agent" in span_by_name and "consumer_agent" in span_by_name:
        producer_id = span_by_name["producer_agent"]["span_id"]
        consumer_sources = span_by_name["consumer_agent"].get("source_span_ids", [])
        check(
            "consumer_agent.source_span_ids contains producer_agent",
            producer_id in consumer_sources,
            f"source_span_ids={consumer_sources}, producer_id={producer_id}",
        )

    # Call blame API
    blame_resp = requests.get(f"{BASE_URL}/traces/{trace_id_1}/blame")
    check("GET /blame returns 200", blame_resp.status_code == 200, blame_resp.text[:300])

    if blame_resp.status_code == 200:
        blame = blame_resp.json()
        orig_names = [o["span_name"] for o in blame.get("originators", [])]
        fail_names = [f["span_name"] for f in blame.get("failure_points", [])]

        check("producer_agent is ORIGINATOR", "producer_agent" in orig_names, f"originators={orig_names}")
        check("consumer_agent is MANIFESTOR", "consumer_agent" in fail_names, f"failure_points={fail_names}")
        check("confidence is not ambiguous", blame.get("confidence") in ("high", "medium"), blame.get("confidence"))

        print(f"  {INFO} human_summary: {blame.get('human_summary', '')[:120]}")


# ════════════════════════════════════════════════════════════════
# Scenario 2: Fan-in — worker_a errors, merge_agent fails
#   Expected: worker_a = ORIGINATOR, merge_agent = MANIFESTOR
# ════════════════════════════════════════════════════════════════

print("\n[Scenario 2] Fan-in — worker_a errors, merge_agent receives it")

@trace(name="worker_a", span_type="agent")
def worker_a_bad():
    raise RuntimeError("worker_a crashed")

@trace(name="worker_b", span_type="agent")
def worker_b_ok():
    return {"data": "fine"}

@trace(name="merge_agent", span_type="agent")
def merge(a, b):
    if a is None:
        raise ValueError("worker_a result was None, cannot merge")
    return {"merged": [a, b]}

@trace(name="pipeline_fanin", span_type="agent")
def pipeline_fanin():
    a = None
    try:
        a = worker_a_bad()
    except Exception:
        pass
    b = worker_b_ok()
    try:
        return merge(a, b)
    except Exception:
        return None

pipeline_fanin()
get_client().flush(timeout=5.0)
time.sleep(2)

resp2 = requests.get(f"{BASE_URL}/traces", params={"name": "pipeline_fanin", "page_size": 5})
traces2 = resp2.json().get("traces", [])
check("fan-in trace ingested", len(traces2) >= 1)

if traces2:
    tid2 = traces2[0]["trace_id"]
    blame2 = requests.get(f"{BASE_URL}/traces/{tid2}/blame").json()
    orig2  = [o["span_name"] for o in blame2.get("originators", [])]
    fail2  = [f["span_name"] for f in blame2.get("failure_points", [])]

    check("worker_a is ORIGINATOR", "worker_a" in orig2, f"originators={orig2}")
    check("merge_agent is MANIFESTOR", "merge_agent" in fail2, f"failure_points={fail2}")
    print(f"  {INFO} human_summary: {blame2.get('human_summary', '')[:120]}")


# ════════════════════════════════════════════════════════════════
# Scenario 3: Clean trace (no errors) — blame returns None/404
# ════════════════════════════════════════════════════════════════

print("\n[Scenario 3] Clean trace — no blame expected")

@trace(name="clean_step_a", span_type="agent")
def step_a():
    return {"value": 42}

@trace(name="clean_step_b", span_type="agent")
def step_b(data):
    return {"doubled": data["value"] * 2}

@trace(name="pipeline_clean", span_type="agent")
def pipeline_clean():
    a = step_a()
    return step_b(a)

pipeline_clean()
get_client().flush(timeout=5.0)
time.sleep(2)

resp3 = requests.get(f"{BASE_URL}/traces", params={"name": "pipeline_clean", "page_size": 5})
traces3 = resp3.json().get("traces", [])
check("clean trace ingested", len(traces3) >= 1)

if traces3:
    tid3 = traces3[0]["trace_id"]
    blame3_resp = requests.get(f"{BASE_URL}/traces/{tid3}/blame")
    # Clean trace → 404 (no bad spans) or empty originators
    if blame3_resp.status_code == 404:
        check("clean trace has no blame (404)", True)
    else:
        blame3 = blame3_resp.json()
        check("clean trace has no originators", blame3.get("originators", []) == [], blame3)


# ════════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════════

print()
if failures:
    print(f"\033[31m{len(failures)} check(s) failed:\033[0m")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"\033[32mAll checks passed.\033[0m")
