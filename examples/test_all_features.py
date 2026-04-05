"""
VerdictLens — Full Feature Test Script

Tests all Phase 1-5 features end-to-end:
  1. Traces & Blame (baseline data)
  2. Datasets & Examples
  3. Evaluations (replay mode)
  4. Workspaces & API Keys
  5. Prompt Playground
  6. Prompt Hub (version, publish, promote, usage stats)

Usage:
    cd verdictlens
    pip install -e ./sdk
    python examples/test_all_features.py
"""

import json
import time
import requests

BASE = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json"}


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def check(label: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def api(method: str, path: str, body=None, expect_status=None):
    url = f"{BASE}{path}"
    fn = getattr(requests, method.lower())
    kwargs = {"headers": HEADERS}
    if body is not None:
        kwargs["json"] = body
    r = fn(url, **kwargs)
    if expect_status and r.status_code != expect_status:
        print(f"  [WARN] {method} {path} returned {r.status_code} (expected {expect_status})")
        print(f"         {r.text[:200]}")
    return r


# =========================================================================
# STEP 0 — Generate some trace data
# =========================================================================

def step0_generate_traces():
    section("STEP 0 — Generate Trace Data")
    from verdictlens import configure, trace

    configure(base_url=BASE)

    @trace(name="test_pipeline", span_type="chain")
    def test_pipeline(query: str) -> dict:
        result = test_agent(query)
        return {"query": query, "result": result}

    @trace(name="test_agent", span_type="agent")
    def test_agent(query: str) -> str:
        return f"Answer to: {query}"

    @trace(name="failing_pipeline", span_type="chain")
    def failing_pipeline(query: str) -> dict:
        bad = bad_agent(query)
        victim = victim_agent(bad)
        return {"result": victim}

    @trace(name="bad_agent", span_type="agent")
    def bad_agent(query: str):
        return None

    @trace(name="victim_agent", span_type="agent")
    def victim_agent(data):
        if data is None:
            raise ValueError("Received null input from upstream")
        return str(data)

    for i in range(3):
        test_pipeline(f"Test query {i+1}")
    print("  Sent 3 success traces")

    for i in range(2):
        try:
            failing_pipeline(f"Failing query {i+1}")
        except Exception:
            pass
    print("  Sent 2 failure traces")

    time.sleep(2)

    r = api("GET", "/traces?limit=5")
    check("Traces ingested", r.status_code == 200 and len(r.json().get("traces", [])) >= 3,
          f"{len(r.json().get('traces', []))} traces found")
    return r.json().get("traces", [])


# =========================================================================
# STEP 1 — Blame Analysis
# =========================================================================

def step1_blame(traces):
    section("STEP 1 — Blame Analysis")

    error_trace = None
    for t in traces:
        if t.get("status") == "error":
            error_trace = t
            break

    if not error_trace:
        print("  [SKIP] No error traces found for blame test")
        return

    r = api("GET", f"/traces/{error_trace['trace_id']}/blame")
    check("Blame endpoint returns 200", r.status_code == 200)

    data = r.json()
    originators = data.get("originators", [])
    has_originator = len(originators) > 0
    check("Blame has originators", has_originator,
          originators[0].get("span_name", "N/A") if has_originator else "none found")
    check("Blame has confidence", data.get("confidence") in ("high", "medium", "ambiguous"),
          data.get("confidence", "N/A"))
    check("Blame has human_summary", len(data.get("human_summary", "")) > 0)
    check("Blame has failure_points", len(data.get("failure_points", [])) > 0)
    check("Blame has propagation_chain", len(data.get("propagation_chain", [])) > 0)


# =========================================================================
# STEP 2 — Datasets & Examples
# =========================================================================

def step2_datasets(traces):
    section("STEP 2 — Datasets & Examples")

    r = api("POST", "/datasets", {"name": "test-golden-set", "description": "Automated test dataset"}, 201)
    check("Create dataset", r.status_code == 201, r.json().get("id", "no id"))
    dataset_id = r.json()["id"]

    r = api("GET", "/datasets")
    check("List datasets", r.status_code == 200 and len(r.json()) >= 1,
          f"{len(r.json())} datasets")

    r = api("POST", f"/datasets/{dataset_id}/examples", {
        "inputs": {"query": "What is AI?"},
        "outputs": {"answer": "Artificial Intelligence is..."},
        "expected": {"answer": "Artificial Intelligence is..."},
        "metadata": {"source": "test"}
    }, 201)
    check("Add example manually", r.status_code == 201,
          r.json().get("id", "no id") if r.status_code == 201 else r.text[:100])

    r = api("POST", f"/datasets/{dataset_id}/examples", {
        "inputs": {"query": "What is ML?"},
        "outputs": {"answer": "Machine Learning is a subset of AI"},
        "expected": {"answer": "Machine Learning is a subset of AI"},
        "metadata": {"source": "test"}
    }, 201)
    check("Add second example", r.status_code == 201)

    r = api("GET", f"/datasets/{dataset_id}/examples")
    check("List examples", r.status_code == 200 and len(r.json()) >= 2,
          f"{len(r.json())} examples")

    if traces:
        trace_id = traces[0]["trace_id"]
        r = api("POST", f"/traces/{trace_id}/to-dataset", {
            "dataset_id": dataset_id,
            "expected": {"answer": "expected output"}
        })
        check("Trace-to-dataset", r.status_code in (200, 201),
              f"status {r.status_code}")

    r = api("GET", f"/datasets/{dataset_id}")
    check("Get dataset detail", r.status_code == 200,
          f"name={r.json().get('name')}, examples={r.json().get('example_count', '?')}")

    return dataset_id


# =========================================================================
# STEP 3 — Evaluations
# =========================================================================

def step3_evaluations(dataset_id):
    section("STEP 3 — Evaluations (Replay Mode)")

    r = api("POST", "/evaluations", {
        "name": "test-eval-exact-match",
        "dataset_id": dataset_id,
        "mode": "replay",
        "scorers": [{"type": "exact_match", "threshold": 0.5}]
    }, 201)
    check("Create evaluation", r.status_code == 201, r.json().get("id", "no id"))
    eval_id = r.json()["id"]

    time.sleep(2)

    r = api("GET", "/evaluations")
    check("List evaluations", r.status_code == 200 and len(r.json()) >= 1,
          f"{len(r.json())} evaluations")

    r = api("GET", f"/evaluations/{eval_id}")
    check("Get evaluation detail", r.status_code == 200,
          f"status={r.json().get('status')}, total={r.json().get('total')}, passed={r.json().get('passed')}")

    r = api("GET", f"/evaluations/{eval_id}/results")
    check("Get evaluation results", r.status_code == 200,
          f"{len(r.json())} results")

    r2 = api("POST", "/evaluations", {
        "name": "test-eval-contains",
        "dataset_id": dataset_id,
        "mode": "replay",
        "scorers": [{"type": "contains", "threshold": 0.5}]
    }, 201)
    eval_id_2 = r2.json()["id"] if r2.status_code == 201 else None

    if eval_id_2:
        time.sleep(2)
        r = api("GET", f"/evaluations/compare?eval_a={eval_id}&eval_b={eval_id_2}")
        check("Compare evaluations", r.status_code == 200,
              f"wins={r.json().get('wins')}, losses={r.json().get('losses')}, ties={r.json().get('ties')}")

    return eval_id


# =========================================================================
# STEP 4 — Workspaces & API Keys
# =========================================================================

def step4_workspaces():
    section("STEP 4 — Workspaces & API Keys")

    r = api("GET", "/workspaces")
    check("List workspaces", r.status_code == 200 and len(r.json()) >= 1,
          f"{len(r.json())} workspaces")

    default_ws = r.json()[0]
    ws_id = default_ws["id"]
    check("Default workspace exists", default_ws["slug"] == "default",
          f"id={ws_id}, slug={default_ws['slug']}")

    r = api("POST", "/workspaces", {
        "name": "Test Team",
        "slug": "test-team",
        "description": "Workspace for automated testing"
    }, 201)
    check("Create workspace", r.status_code == 201, r.json().get("id", ""))
    new_ws_id = r.json()["id"]

    r = api("POST", f"/workspaces/{new_ws_id}/api-keys", {
        "name": "test-key",
        "workspace_id": new_ws_id
    }, 201)
    check("Create API key", r.status_code == 201)
    if r.status_code == 201:
        key_data = r.json()
        check("API key has prefix", len(key_data.get("key_prefix", "")) > 0, key_data.get("key_prefix"))
        check("API key shown once", key_data.get("key") is not None and len(key_data["key"]) > 10,
              f"{key_data.get('key', '')[:12]}...")
        key_id = key_data["id"]

        r = api("GET", f"/workspaces/{new_ws_id}/api-keys")
        check("List API keys", r.status_code == 200 and len(r.json()) >= 1,
              f"{len(r.json())} keys")

        r = api("DELETE", f"/workspaces/{new_ws_id}/api-keys/{key_id}")
        check("Delete API key", r.status_code == 200)

    return ws_id


# =========================================================================
# STEP 5 — Prompt Playground
# =========================================================================

def step5_playground():
    section("STEP 5 — Prompt Playground")

    r = api("POST", "/playground/run", {
        "prompt": "Say exactly: Hello from VerdictLens playground test",
        "model": "gpt-4o-mini",
        "temperature": 0.0,
        "max_tokens": 100
    })
    check("Playground run", r.status_code == 200)
    data = r.json()
    if data.get("error"):
        check("Playground LLM call", False, f"error: {data['error'][:100]}")
    else:
        check("Playground got output", data.get("output") is not None and len(str(data["output"])) > 0,
              f"output: {str(data.get('output', ''))[:80]}...")
        check("Playground has latency", data.get("latency_ms", 0) > 0, f"{data.get('latency_ms', 0):.0f}ms")
        check("Playground has tokens", data.get("total_tokens", 0) > 0, f"{data.get('total_tokens', 0)} tokens")

    r = api("POST", "/playground/run", {"prompt": "", "model": "gpt-4o-mini"})
    check("Empty prompt rejected", r.status_code == 400, "safety layer working")

    r = api("POST", "/playground/prompts", {
        "name": "greeting-prompt",
        "content": "You are a helpful assistant. Greet the user warmly.",
        "model": "gpt-4o-mini",
        "temperature": 0.7,
        "max_tokens": 256,
        "tags": ["test", "greeting"]
    }, 201)
    check("Save prompt version", r.status_code == 201)
    version_id_1 = r.json()["id"] if r.status_code == 201 else None

    r = api("POST", "/playground/prompts", {
        "name": "greeting-prompt",
        "content": "You are a professional assistant. Greet the user formally.",
        "model": "gpt-4o",
        "temperature": 0.3,
        "max_tokens": 512,
        "parent_id": version_id_1,
        "tags": ["test", "greeting", "formal"]
    }, 201)
    check("Save prompt v2", r.status_code == 201,
          f"version_number={r.json().get('version_number')}")
    version_id_2 = r.json()["id"] if r.status_code == 201 else None

    r = api("GET", "/playground/prompts")
    check("List prompts", r.status_code == 200 and len(r.json()) >= 2,
          f"{len(r.json())} prompts")

    if version_id_1:
        r = api("GET", f"/playground/prompts/{version_id_1}")
        check("Get prompt version", r.status_code == 200, f"name={r.json().get('name')}")

    return version_id_1, version_id_2


# =========================================================================
# STEP 6 — Prompt Hub
# =========================================================================

def step6_prompt_hub(version_id_1, version_id_2):
    section("STEP 6 — Prompt Hub")

    if not version_id_2:
        print("  [SKIP] No prompt versions to test with")
        return

    r = api("POST", f"/playground/prompts/{version_id_2}/publish")
    check("Publish prompt", r.status_code == 200)

    r = api("GET", "/prompt-hub")
    check("List hub prompts", r.status_code == 200 and len(r.json()) >= 1,
          f"{len(r.json())} published prompts")

    if r.status_code == 200 and len(r.json()) > 0:
        entry = r.json()[0]
        check("Hub entry has fields",
              all(k in entry for k in ("name", "model", "version_number", "total_versions")),
              f"name={entry.get('name')}, v{entry.get('version_number')}, {entry.get('total_versions')} versions")

    r = api("GET", "/playground/prompts/greeting-prompt/history")
    check("Version history", r.status_code == 200,
          f"total_versions={r.json().get('total_versions')}")
    if r.status_code == 200:
        history = r.json()
        check("History has versions list", len(history.get("versions", [])) >= 2,
              f"{len(history.get('versions', []))} versions")

    if version_id_1:
        r = api("POST", f"/playground/prompts/{version_id_1}/promote")
        check("Promote older version", r.status_code == 200,
              f"new version_number={r.json().get('version_number')}")

    r = api("GET", f"/prompt-hub/greeting-prompt/usage")
    check("Usage stats endpoint", r.status_code == 200,
          f"total_runs={r.json().get('total_runs')}")

    r = api("POST", f"/playground/prompts/{version_id_2}/unpublish")
    check("Unpublish prompt", r.status_code == 200)

    r = api("GET", "/prompt-hub")
    published_count = len(r.json()) if r.status_code == 200 else -1
    check("Hub updated after unpublish", r.status_code == 200,
          f"{published_count} published")


# =========================================================================
# STEP 7 — Cleanup
# =========================================================================

def step7_summary(passed, total):
    section("SUMMARY")
    print(f"  Passed: {passed}/{total}")
    if passed == total:
        print("  ALL FEATURES WORKING!")
    else:
        print(f"  {total - passed} test(s) need attention")
    print()


# =========================================================================
# Run
# =========================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  VerdictLens — Full Feature Test")
    print("="*60)

    r = requests.get(f"{BASE}/health")
    if r.status_code != 200:
        print("  API not reachable. Run: docker compose up -d --build")
        exit(1)
    print(f"  API healthy at {BASE}")

    results = []

    traces = step0_generate_traces()
    step1_blame(traces)
    dataset_id = step2_datasets(traces)
    step3_evaluations(dataset_id)
    step4_workspaces()
    v1, v2 = step5_playground()
    step6_prompt_hub(v1, v2)

    section("DONE")
    print("  Open http://localhost:3000 to see everything in the UI:")
    print("    - Dashboard: trace metrics and recent traces")
    print("    - Traces: all traces with span trees and blame")
    print("    - Datasets: 'test-golden-set' with examples")
    print("    - Evaluations: 'test-eval-exact-match' and 'test-eval-contains'")
    print("    - Playground: run prompts, saved 'greeting-prompt' versions")
    print("    - Prompt Hub: published prompts (if any remain published)")
    print("    - Workspaces: 'Default Workspace' + 'Test Team'")
    print()
