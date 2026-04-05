"""
Integration test: Real LLM calls → SDK traces → ClickHouse → Blame API.

Runs 10 real-world scenarios through Groq, ingests traces, waits for
them to appear in the backend, then calls the blame API and validates
the results.

Usage:
    pip install -e ./sdk openai requests python-dotenv
    python examples/test_blame_real.py

Requires:
    - GROQ_API_KEY in .env
    - docker compose up (backend + clickhouse running)
"""

import os
import sys
import time
import asyncio
import requests
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

from openai import OpenAI, AsyncOpenAI
from verdictlens import configure, trace, wrap_openai, get_client

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("GROQ_API_KEY not set. Get one free at https://console.groq.com/keys")
    sys.exit(1)

BASE_URL = "http://localhost:8000"
configure(base_url=BASE_URL)

client = wrap_openai(OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
))

async_client = wrap_openai(AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
))

MODEL = "llama-3.1-8b-instant"

passed = 0
failed = 0
errors = []


def check(condition: bool, msg: str):
    global passed, failed
    if condition:
        passed += 1
        print(f"    ✓ {msg}")
    else:
        failed += 1
        errors.append(msg)
        print(f"    ✗ FAIL: {msg}")


def flush_and_wait():
    get_client().flush(timeout=10.0)
    time.sleep(2)


def get_blame(trace_name: str) -> dict | None:
    """Find the most recent trace by name and fetch its blame."""
    resp = requests.get(f"{BASE_URL}/traces", params={"name": trace_name, "page_size": 1})
    if resp.status_code != 200:
        return None
    traces = resp.json().get("traces", [])
    if not traces:
        return None
    trace_id = traces[0]["trace_id"]
    blame_resp = requests.get(f"{BASE_URL}/traces/{trace_id}/blame")
    if blame_resp.status_code == 422:
        return {"no_blame": True, "trace_id": trace_id}
    if blame_resp.status_code != 200:
        return None
    result = blame_resp.json()
    result["trace_id"] = trace_id
    return result


def get_trace_detail(trace_name: str) -> dict | None:
    resp = requests.get(f"{BASE_URL}/traces", params={"name": trace_name, "page_size": 1})
    if resp.status_code != 200:
        return None
    traces = resp.json().get("traces", [])
    if not traces:
        return None
    trace_id = traces[0]["trace_id"]
    detail = requests.get(f"{BASE_URL}/traces/{trace_id}")
    if detail.status_code != 200:
        return None
    return detail.json()


# ══════════════════════════════════════════════════════════════════
# SCENARIO 1: Null retriever poisons downstream generator
# Real Groq call for generator, but retriever returns None
# ══════════════════════════════════════════════════════════════════

@trace(name="s1_null_poison", span_type="chain")
def s1_null_poison():
    context = s1_retriever()
    answer = s1_generator(context)
    return {"context": context, "answer": answer}

@trace(name="s1_retriever", span_type="retrieval")
def s1_retriever():
    return None

@trace(name="s1_generator", span_type="agent")
def s1_generator(context):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Summarize the context."},
            {"role": "user", "content": str(context)},
        ],
        max_tokens=100,
    )
    return resp.choices[0].message.content


def test_scenario_1():
    print("\n[1/10] Null retriever poisons generator (real LLM)")
    s1_null_poison()
    flush_and_wait()

    blame = get_blame("s1_null_poison")
    check(blame is not None and "no_blame" not in blame,
          "Blame should fire (retriever output is null)")
    if blame and "originators" in blame:
        orig_names = [o["span_name"] for o in blame["originators"]]
        check("s1_retriever" in orig_names,
              "s1_retriever should be originator")
        check("s1_generator" not in orig_names,
              "s1_generator must NOT be originator (it's a victim)")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 2: Child LLM error → parent agent fails
# Force an error by sending an absurdly long prompt
# ══════════════════════════════════════════════════════════════════

@trace(name="s2_llm_error", span_type="chain")
def s2_llm_error():
    plan = s2_planner()
    result = s2_executor(plan)
    return {"plan": plan, "result": result}

@trace(name="s2_planner", span_type="agent")
def s2_planner():
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "x" * 50000}],
            max_tokens=10,
        )
        return resp.choices[0].message.content
    except Exception:
        return None

@trace(name="s2_executor", span_type="agent")
def s2_executor(plan):
    if plan is None:
        raise ValueError("No plan provided — upstream planner failed")
    return f"Executed: {plan}"


def test_scenario_2():
    print("\n[2/10] Child LLM error → parent agent fails (real LLM)")
    try:
        s2_llm_error()
    except Exception:
        pass
    flush_and_wait()

    blame = get_blame("s2_llm_error")
    check(blame is not None and "no_blame" not in blame,
          "Blame should fire (planner produced null or executor errored)")
    if blame and "originators" in blame:
        orig_names = [o["span_name"] for o in blame["originators"]]
        check("s2_planner" in orig_names or "s2_executor" in orig_names,
              "Planner or executor should be originator")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 3: Multi-agent debate — all agents succeed
# Should produce NO blame
# ══════════════════════════════════════════════════════════════════

@trace(name="s3_clean_debate", span_type="chain")
def s3_clean_debate():
    pro = s3_argue("for")
    con = s3_argue("against")
    verdict = s3_judge(pro, con)
    return {"pro": pro, "con": con, "verdict": verdict}

@trace(name="s3_argue", span_type="agent")
def s3_argue(stance: str):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": f"Argue {stance} AI in one sentence."},
            {"role": "user", "content": "Is AI beneficial for humanity?"},
        ],
        max_tokens=100,
    )
    return resp.choices[0].message.content

@trace(name="s3_judge", span_type="agent")
def s3_judge(pro: str, con: str):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Pick the stronger argument in one sentence."},
            {"role": "user", "content": f"For: {pro}\nAgainst: {con}"},
        ],
        max_tokens=100,
    )
    return resp.choices[0].message.content


def test_scenario_3():
    print("\n[3/10] Clean debate — no blame expected (real LLM)")
    s3_clean_debate()
    flush_and_wait()

    blame = get_blame("s3_clean_debate")
    check(blame is not None and blame.get("no_blame") is True,
          "No blame should fire — all agents succeeded with valid outputs")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 4: Parallel analysis — one item returns empty
# ══════════════════════════════════════════════════════════════════

@trace(name="s4_partial_batch", span_type="chain")
async def s4_partial_batch():
    results = await asyncio.gather(
        s4_analyze("Bitcoin price trends"),
        s4_analyze_empty(),
        s4_analyze("Climate policy changes"),
    )
    return list(results)

@trace(name="s4_analyze", span_type="agent")
async def s4_analyze(topic: str):
    resp = await async_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": f"One-sentence analysis of: {topic}"}],
        max_tokens=80,
    )
    return resp.choices[0].message.content

@trace(name="s4_analyze_empty", span_type="agent")
async def s4_analyze_empty():
    return None


def test_scenario_4():
    print("\n[4/10] Partial batch — one null item (real LLM)")
    asyncio.run(s4_partial_batch())
    flush_and_wait()

    blame = get_blame("s4_partial_batch")
    check(blame is not None and "no_blame" not in blame,
          "Blame should fire — s4_analyze_empty returned null")
    if blame and "originators" in blame:
        orig_names = [o["span_name"] for o in blame["originators"]]
        check("s4_analyze_empty" in orig_names,
              "s4_analyze_empty should be originator")
        check("s4_analyze" not in orig_names,
              "Successful s4_analyze spans must NOT be blamed")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 5: Research pipeline with graceful recovery
# Retriever returns null, but generator handles it
# ══════════════════════════════════════════════════════════════════

@trace(name="s5_graceful_recovery", span_type="chain")
def s5_graceful_recovery():
    docs = s5_retriever()
    answer = s5_fallback_generator(docs)
    safe = s5_guardrail(answer)
    return {"answer": safe}

@trace(name="s5_retriever", span_type="retrieval")
def s5_retriever():
    return None

@trace(name="s5_fallback_generator", span_type="agent")
def s5_fallback_generator(docs):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "If context is null, say 'I don't have enough information.'"},
            {"role": "user", "content": f"Context: {docs}. Answer the user question."},
        ],
        max_tokens=100,
    )
    return resp.choices[0].message.content

@trace(name="s5_guardrail", span_type="agent")
def s5_guardrail(text: str):
    return f"[SAFE] {text}"


def test_scenario_5():
    print("\n[5/10] Graceful recovery — retriever null but guardrail recovers (real LLM)")
    s5_graceful_recovery()
    flush_and_wait()

    blame = get_blame("s5_graceful_recovery")
    check(blame is not None and "no_blame" not in blame,
          "Blame should fire — s5_retriever output is null")
    if blame and "originators" in blame:
        orig_names = [o["span_name"] for o in blame["originators"]]
        check("s5_retriever" in orig_names,
              "s5_retriever should be originator")
        blamed_all = set()
        for lst in [blame["originators"], blame.get("failure_points", []),
                     blame.get("secondary_contributors", [])]:
            for item in lst:
                blamed_all.add(item["span_name"])
        check("s5_guardrail" not in blamed_all,
              "s5_guardrail succeeded — must NOT be blamed")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 6: Deep chain — LLM → agent → formatter → validator
# LLM produces garbage → propagates down
# ══════════════════════════════════════════════════════════════════

@trace(name="s6_deep_chain", span_type="chain")
def s6_deep_chain():
    raw = s6_research()
    formatted = s6_format(raw)
    validated = s6_validate(formatted)
    return {"result": validated}

@trace(name="s6_research", span_type="agent")
def s6_research():
    return None

@trace(name="s6_format", span_type="agent")
def s6_format(raw):
    if raw is None:
        return None
    return f"Formatted: {raw}"

@trace(name="s6_validate", span_type="agent")
def s6_validate(data):
    if data is None:
        raise ValueError("Validation failed: input is null")
    return f"Valid: {data}"


def test_scenario_6():
    print("\n[6/10] Deep chain — null propagates through formatter to validator")
    try:
        s6_deep_chain()
    except Exception:
        pass
    flush_and_wait()

    blame = get_blame("s6_deep_chain")
    check(blame is not None and "no_blame" not in blame,
          "Blame should fire")
    if blame and "originators" in blame:
        orig_names = [o["span_name"] for o in blame["originators"]]
        check("s6_research" in orig_names,
              "s6_research (first null) should be originator")
        check("s6_validate" not in orig_names,
              "s6_validate (end of chain) should NOT be originator")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 7: Retry pattern — same operation 3 times
# ══════════════════════════════════════════════════════════════════

@trace(name="s7_retry_pattern", span_type="chain")
def s7_retry_pattern():
    for i in range(3):
        result = s7_flaky_tool(i)
        if result is not None:
            return {"result": result, "attempts": i + 1}
    return {"result": None, "attempts": 3}

@trace(name="s7_flaky_tool", span_type="tool")
def s7_flaky_tool(attempt: int):
    return None


def test_scenario_7():
    print("\n[7/10] Retry pattern — 3 attempts of same flaky tool")
    s7_retry_pattern()
    flush_and_wait()

    blame = get_blame("s7_retry_pattern")
    check(blame is not None and "no_blame" not in blame,
          "Blame should fire — all tool attempts returned null")
    if blame and "originators" in blame:
        orig_names = [o["span_name"] for o in blame["originators"]]
        check("s7_flaky_tool" in orig_names,
              "s7_flaky_tool should be originator")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 8: Two independent LLM calls both succeed
# Proves engine stays quiet on healthy traces
# ══════════════════════════════════════════════════════════════════

@trace(name="s8_both_healthy", span_type="chain")
def s8_both_healthy():
    a = s8_agent_a()
    b = s8_agent_b()
    return {"a": a, "b": b}

@trace(name="s8_agent_a", span_type="agent")
def s8_agent_a():
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Say hello in French."}],
        max_tokens=30,
    )
    return resp.choices[0].message.content

@trace(name="s8_agent_b", span_type="agent")
def s8_agent_b():
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Say hello in Spanish."}],
        max_tokens=30,
    )
    return resp.choices[0].message.content


def test_scenario_8():
    print("\n[8/10] Both agents healthy — no blame expected (real LLM)")
    s8_both_healthy()
    flush_and_wait()

    blame = get_blame("s8_both_healthy")
    check(blame is not None and blame.get("no_blame") is True,
          "No blame should fire — both agents succeeded")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 9: Exception in one branch, other branch succeeds
# ══════════════════════════════════════════════════════════════════

@trace(name="s9_one_branch_fails", span_type="chain")
def s9_one_branch_fails():
    good = s9_good_branch()
    try:
        bad = s9_bad_branch()
    except Exception:
        bad = None
    return {"good": good, "bad": bad}

@trace(name="s9_good_branch", span_type="agent")
def s9_good_branch():
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "What is 2+2?"}],
        max_tokens=20,
    )
    return resp.choices[0].message.content

@trace(name="s9_bad_branch", span_type="agent")
def s9_bad_branch():
    raise RuntimeError("Simulated failure in bad branch")


def test_scenario_9():
    print("\n[9/10] One branch fails, other succeeds (real LLM + simulated error)")
    s9_one_branch_fails()
    flush_and_wait()

    blame = get_blame("s9_one_branch_fails")
    check(blame is not None and "no_blame" not in blame,
          "Blame should fire — s9_bad_branch threw an error")
    if blame and "originators" in blame:
        orig_names = [o["span_name"] for o in blame["originators"]]
        check("s9_bad_branch" in orig_names,
              "s9_bad_branch should be originator")
        check("s9_good_branch" not in orig_names,
              "s9_good_branch succeeded — must NOT be blamed")
        check(blame.get("confidence") == "high",
              "Single clear failure should be high confidence")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 10: Complex 3-level real pipeline
# research_agent → (real LLM) → summary_agent → (real LLM)
# but research returns null → summary gets garbage
# ══════════════════════════════════════════════════════════════════

@trace(name="s10_complex_pipeline", span_type="chain")
def s10_complex_pipeline():
    research = s10_research_agent()
    summary = s10_summary_agent(research)
    decision = s10_decision_agent(summary)
    return {"research": research, "summary": summary, "decision": decision}

@trace(name="s10_research_agent", span_type="agent")
def s10_research_agent():
    return None

@trace(name="s10_summary_agent", span_type="agent")
def s10_summary_agent(findings):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Summarize these findings. If null, say 'No findings available.'"},
            {"role": "user", "content": str(findings)},
        ],
        max_tokens=100,
    )
    return resp.choices[0].message.content

@trace(name="s10_decision_agent", span_type="agent")
def s10_decision_agent(summary: str):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Based on this summary, make a yes/no decision."},
            {"role": "user", "content": summary},
        ],
        max_tokens=50,
    )
    return resp.choices[0].message.content


def test_scenario_10():
    print("\n[10/10] Complex 3-level pipeline — null research propagates (real LLM)")
    s10_complex_pipeline()
    flush_and_wait()

    blame = get_blame("s10_complex_pipeline")
    check(blame is not None and "no_blame" not in blame,
          "Blame should fire — s10_research_agent returned null")
    if blame and "originators" in blame:
        orig_names = [o["span_name"] for o in blame["originators"]]
        check("s10_research_agent" in orig_names,
              "s10_research_agent should be originator (introduced null)")
        check("s10_decision_agent" not in orig_names,
              "s10_decision_agent is downstream — must NOT be originator")
        check(len(blame.get("propagation_chain", [])) >= 1,
              "Propagation chain should describe the failure flow")

    detail = get_trace_detail("s10_complex_pipeline")
    if detail:
        spans = detail.get("spans", [])
        llm_spans = [s for s in spans if "chat.completions" in s.get("name", "")]
        check(len(llm_spans) >= 2,
              f"Should have ≥2 real LLM spans (got {len(llm_spans)})")
        for ls in llm_spans:
            check(ls.get("model") is not None,
                  f"LLM span '{ls['name']}' should have model captured")
            tokens = ls.get("token_usage") or {}
            total = tokens.get("total_tokens")
            check(total is not None and total > 0,
                  f"LLM span '{ls['name']}' should have tokens captured (got {total})")


# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("  VerdictLens Blame Engine — Real LLM Integration Tests")
    print(f"  Model: {MODEL} (Groq)")
    print(f"  Backend: {BASE_URL}")
    print("=" * 65)

    test_scenario_1()
    test_scenario_2()
    test_scenario_3()
    test_scenario_4()
    test_scenario_5()
    test_scenario_6()
    test_scenario_7()
    test_scenario_8()
    test_scenario_9()
    test_scenario_10()

    print("\n" + "=" * 65)
    print(f"  RESULTS: {passed} passed, {failed} failed")
    if errors:
        print(f"\n  FAILURES:")
        for e in errors:
            print(f"    ✗ {e}")
    else:
        print("  ALL TESTS PASSED")
    print("=" * 65)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
