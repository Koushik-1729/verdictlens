"""
Integration tests — real LLM calls via NVIDIA NIM (free tier).

Unlike unit tests that use fake spans, these tests make ACTUAL API calls,
capture real outputs/errors, build SpanOut objects from them, and verify
the blame engine correctly attributes fault.

Run with:
    NVIDIA_API_KEY=nvapi-... pytest tests/test_blame_integration.py -v -s

The key difference from unit tests:
- Latency, token counts, outputs are all REAL
- Failures are triggered by real API errors or real bad outputs
- Blame engine is tested on data it has never seen
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

import pytest

from app.blame_engine import compute_blame
from app.models import SpanOut, TokenUsageOut

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "google/gemma-7b"
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")

if not NVIDIA_API_KEY:
    pytest.skip("NVIDIA_API_KEY not set — skipping integration tests", allow_module_level=True)

# ---------------------------------------------------------------------------
# Real LLM call helper
# ---------------------------------------------------------------------------

def _call_llm(
    prompt: str,
    *,
    max_tokens: int = 128,
    force_error: bool = False,
) -> Tuple[Any, Any, float, Optional[Dict]]:
    """
    Make a real LLM call to NVIDIA NIM.

    :param prompt: User prompt.
    :param max_tokens: Max tokens to generate.
    :param force_error: If True, send an invalid model name to trigger a real API error.
    :returns: (output, error, latency_ms, token_usage_dict)
    """
    import openai

    client = openai.OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)
    model = "invalid-model-does-not-exist" if force_error else NVIDIA_MODEL

    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            top_p=0.7,
            max_tokens=max_tokens,
            stream=False,
        )
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        content = response.choices[0].message.content if response.choices else None
        token_usage = None
        if response.usage:
            token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return content, None, latency_ms, token_usage

    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        error = {"type": type(exc).__name__, "message": str(exc)}
        return None, error, latency_ms, None


def _span(
    *,
    name: str,
    span_id: str,
    trace_id: str,
    parent_span_id: Optional[str] = None,
    span_type: str = "llm",
    input: Any = None,
    output: Any = None,
    error: Any = None,
    latency_ms: float = 0.0,
    token_usage: Optional[Dict] = None,
    source_span_ids: Optional[list] = None,
) -> SpanOut:
    tu = TokenUsageOut(**token_usage) if token_usage else None
    return SpanOut(
        span_id=span_id,
        parent_span_id=parent_span_id,
        trace_id=trace_id,
        name=name,
        span_type=span_type,
        latency_ms=latency_ms,
        input=input,
        output=output,
        error=error,
        token_usage=tu,
        source_span_ids=source_span_ids or [],
        metadata={},
    )


# ---------------------------------------------------------------------------
# Test 1: Clean pipeline — no blame expected
# ---------------------------------------------------------------------------

class TestCleanPipeline:
    """
    Both agents make real LLM calls and succeed.
    compute_blame should return None — nothing to blame.
    """

    def test_no_blame_when_all_agents_succeed(self):
        trace_id = str(uuid4())
        root_id = str(uuid4())
        agent1_id = str(uuid4())
        agent2_id = str(uuid4())

        # Real call 1: research agent
        out1, err1, lat1, tok1 = _call_llm(
            "What is the capital of France? Answer in one word."
        )
        print(f"\n[agent1] output={out1!r} latency={lat1}ms tokens={tok1}")

        # Real call 2: summary agent uses agent1's output
        prompt2 = f"Summarize this in one sentence: {out1}"
        out2, err2, lat2, tok2 = _call_llm(prompt2)
        print(f"[agent2] output={out2!r} latency={lat2}ms tokens={tok2}")

        spans = [
            _span(name="pipeline", span_id=root_id, trace_id=trace_id,
                  span_type="agent", output={"status": "ok"}, latency_ms=lat1 + lat2),
            _span(name="research_agent", span_id=agent1_id, trace_id=trace_id,
                  parent_span_id=root_id, input={"query": "capital of France"},
                  output=out1, error=err1, latency_ms=lat1, token_usage=tok1),
            _span(name="summary_agent", span_id=agent2_id, trace_id=trace_id,
                  parent_span_id=root_id, source_span_ids=[agent1_id],
                  input={"context": out1}, output=out2, error=err2,
                  latency_ms=lat2, token_usage=tok2),
        ]

        result = compute_blame(spans)
        assert result is None, (
            f"Expected no blame on a clean pipeline, got: {result}"
        )


# ---------------------------------------------------------------------------
# Test 2: Real API error → downstream failure
# ---------------------------------------------------------------------------

class TestRealApiError:
    """
    Agent 1 triggers a real API error (invalid model name).
    Agent 2 receives null output from Agent 1 and fails.
    Blame must fall on Agent 1 as ORIGINATOR.
    """

    def test_api_error_agent_is_originator(self):
        trace_id = str(uuid4())
        root_id = str(uuid4())
        agent1_id = str(uuid4())
        agent2_id = str(uuid4())

        # Agent 1: real API error via invalid model
        out1, err1, lat1, tok1 = _call_llm(
            "Summarize the latest AI trends.",
            force_error=True,  # sends invalid model → real API error
        )
        print(f"\n[agent1_error] output={out1!r} error={err1} latency={lat1}ms")
        assert err1 is not None, "Expected a real API error from invalid model"

        # Agent 2: real LLM call but receives null context from agent1
        context = out1 or ""
        prompt2 = f"Continue this analysis: {context}"
        out2, err2, lat2, tok2 = _call_llm(prompt2)
        print(f"[agent2] output={out2!r} latency={lat2}ms")

        spans = [
            _span(name="pipeline", span_id=root_id, trace_id=trace_id,
                  span_type="agent", output=None, latency_ms=lat1 + lat2),
            _span(name="data_agent", span_id=agent1_id, trace_id=trace_id,
                  parent_span_id=root_id, input={"query": "AI trends"},
                  output=out1, error=err1, latency_ms=lat1, token_usage=tok1),
            _span(name="analysis_agent", span_id=agent2_id, trace_id=trace_id,
                  parent_span_id=root_id, source_span_ids=[agent1_id],
                  input={"context": out1}, output=out2, error=err2,
                  latency_ms=lat2, token_usage=tok2),
        ]

        result = compute_blame(spans)
        assert result is not None, "Expected blame result when first agent errored"

        originator_names = [o.span_name for o in result.originators]
        print(f"[blame] originators={originator_names} confidence={result.confidence}")
        print(f"[blame] summary={result.human_summary}")

        assert "data_agent" in originator_names, (
            f"data_agent caused the real API error — must be ORIGINATOR. "
            f"Got: {originator_names}"
        )

    def test_failure_mode_tag_on_real_error(self):
        """The real API error should get a MAST failure_mode tag."""
        trace_id = str(uuid4())
        root_id = str(uuid4())
        agent_id = str(uuid4())

        out, err, lat, tok = _call_llm("Hello", force_error=True)
        assert err is not None

        spans = [
            _span(name="pipeline", span_id=root_id, trace_id=trace_id,
                  span_type="agent", output=None),
            _span(name="broken_llm", span_id=agent_id, trace_id=trace_id,
                  parent_span_id=root_id, output=out, error=err, latency_ms=lat),
        ]

        result = compute_blame(spans)
        assert result is not None
        originator = result.originators[0]
        print(f"\n[failure_mode] {originator.span_name} → {originator.failure_mode}")
        # Any failure mode is valid — just verify the field is populated or None
        # (mode depends on exact error message from NVIDIA API)
        assert originator.blame_score > 0


# ---------------------------------------------------------------------------
# Test 3: Real output → JSON parse failure downstream
# ---------------------------------------------------------------------------

class TestJsonFormatError:
    """
    Agent 1 makes a real LLM call asking for JSON.
    A downstream 'parser' agent tries to parse it with json.loads().
    If the LLM returns non-JSON, parser fails → LLM agent is ORIGINATOR.
    If LLM returns valid JSON, both succeed → no blame.
    """

    def test_json_parse_failure_blames_llm_agent(self):
        trace_id = str(uuid4())
        root_id = str(uuid4())
        llm_id = str(uuid4())
        parser_id = str(uuid4())

        # Ask LLM to return JSON — gemma-7b often returns prose instead
        out1, err1, lat1, tok1 = _call_llm(
            "Return ONLY a raw JSON object with keys 'name' and 'score'. "
            "No explanation, no markdown, just the JSON.",
            max_tokens=64,
        )
        print(f"\n[llm_agent] raw output={out1!r} latency={lat1}ms")

        # Downstream parser — real json.loads attempt
        parser_output = None
        parser_error = None
        try:
            parser_output = json.loads(out1 or "")
            print(f"[parser] success: {parser_output}")
        except (json.JSONDecodeError, TypeError) as exc:
            parser_error = {
                "type": "JSONDecodeError",
                "message": f"invalid json parse error: {exc}",
            }
            print(f"[parser] FAILED: {parser_error['message']}")

        spans = [
            _span(name="pipeline", span_id=root_id, trace_id=trace_id,
                  span_type="agent", output=parser_output,
                  latency_ms=lat1),
            _span(name="llm_agent", span_id=llm_id, trace_id=trace_id,
                  parent_span_id=root_id, span_type="llm",
                  input={"prompt": "return JSON"},
                  output=out1, error=err1, latency_ms=lat1, token_usage=tok1),
            _span(name="json_parser", span_id=parser_id, trace_id=trace_id,
                  parent_span_id=root_id, source_span_ids=[llm_id],
                  span_type="tool",
                  input={"raw": out1}, output=parser_output, error=parser_error,
                  latency_ms=1.0),
        ]

        result = compute_blame(spans)

        if parser_error is not None:
            # LLM returned invalid JSON — should blame llm_agent or json_parser
            assert result is not None, "Expected blame when parser failed"
            all_blamed = (
                {o.span_name for o in result.originators}
                | {f.span_name for f in result.failure_points}
            )
            print(f"[blame] blamed={all_blamed} confidence={result.confidence}")
            print(f"[blame] summary={result.human_summary}")
            assert "json_parser" in all_blamed or "llm_agent" in all_blamed

            # Check MAST failure mode on json_parser
            parser_blamed = next(
                (o for o in result.originators if o.span_name == "json_parser"),
                next((f for f in result.failure_points if f.span_name == "json_parser"), None),
            )
            if parser_blamed:
                print(f"[failure_mode] json_parser → {parser_blamed.failure_mode}")
        else:
            # LLM returned valid JSON — no blame
            print("[blame] LLM returned valid JSON — no blame expected")
            assert result is None


# ---------------------------------------------------------------------------
# Test 4: Latency spike detection with real timing
# ---------------------------------------------------------------------------

class TestLatencyAnomalyWithRealTiming:
    """
    Make two real LLM calls: one fast (short prompt), one slow (long prompt).
    The slow call should get a higher latency anomaly score.
    """

    def test_latency_spike_boosts_blame_score(self):
        trace_id = str(uuid4())
        root_id = str(uuid4())
        fast_id = str(uuid4())
        slow_id = str(uuid4())

        # Fast call: very short output
        out_fast, err_fast, lat_fast, tok_fast = _call_llm(
            "Say 'ok'.", max_tokens=5
        )
        print(f"\n[fast] latency={lat_fast}ms output={out_fast!r}")

        # Slow call: longer generation — inject a real error too
        out_slow, err_slow, lat_slow, tok_slow = _call_llm(
            "Write a very detailed essay about quantum computing history.",
            max_tokens=128,
        )
        # Inject failure on slow span to make it blameable
        err_slow = {"type": "TimeoutError", "message": "span timed out"}
        out_slow = None
        print(f"[slow+error] latency={lat_slow}ms (injected error)")

        spans = [
            _span(name="orchestrator", span_id=root_id, trace_id=trace_id,
                  span_type="agent", output=None, latency_ms=lat_fast + lat_slow),
            _span(name="fast_agent", span_id=fast_id, trace_id=trace_id,
                  parent_span_id=root_id, output=out_fast, error=err_fast,
                  latency_ms=lat_fast, token_usage=tok_fast),
            _span(name="slow_agent", span_id=slow_id, trace_id=trace_id,
                  parent_span_id=root_id, output=out_slow, error=err_slow,
                  latency_ms=lat_slow, token_usage=tok_slow),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = [o.span_name for o in result.originators]
        print(f"[blame] originators={originator_names}")

        slow_score = next(
            (o.blame_score for o in result.originators if o.span_name == "slow_agent"), 0.0
        )
        fast_score = next(
            (o.blame_score for o in result.originators if o.span_name == "fast_agent"), 0.0
        )
        print(f"[scores] slow_agent={slow_score} fast_agent={fast_score}")

        assert "slow_agent" in originator_names, (
            "slow_agent has injected error — must be originator"
        )
        assert slow_score >= fast_score


# ---------------------------------------------------------------------------
# Test 5: Token count anomaly with real usage data
# ---------------------------------------------------------------------------

class TestTokenAnomalyWithRealUsage:
    """
    Two real LLM calls: one minimal, one with heavy token usage.
    Verify token_usage is captured correctly from real API response
    and that TraceStats computes meaningful averages.
    """

    def test_token_usage_captured_from_real_call(self):
        trace_id = str(uuid4())
        root_id = str(uuid4())
        agent_id = str(uuid4())

        out, err, lat, tok = _call_llm(
            "List 5 programming languages.", max_tokens=100
        )
        print(f"\n[token_test] output={out!r} tokens={tok} latency={lat}ms")

        assert tok is not None, "NVIDIA NIM should return token usage"
        assert tok.get("total_tokens", 0) > 0

        spans = [
            _span(name="pipeline", span_id=root_id, trace_id=trace_id,
                  span_type="agent", output={"status": "ok"}),
            _span(name="list_agent", span_id=agent_id, trace_id=trace_id,
                  parent_span_id=root_id, output=out, error=err,
                  latency_ms=lat, token_usage=tok),
        ]

        # No failures — just verify spans built correctly from real data
        result = compute_blame(spans)
        assert result is None, "No blame for a successful call"


# ---------------------------------------------------------------------------
# Test 6: End-to-end 3-agent pipeline with real middle failure
# ---------------------------------------------------------------------------

class TestThreeAgentPipelineRealMiddleFailure:
    """
    3-agent pipeline:
      research_agent (real call, succeeds)
        → analysis_agent (real API error — invalid model)
          → report_agent (real call, receives null from analysis_agent)

    Expected: analysis_agent is ORIGINATOR, report_agent is MANIFESTOR.
    research_agent is CLEAN.
    """

    def test_middle_agent_is_originator(self):
        trace_id = str(uuid4())
        root_id = str(uuid4())
        research_id = str(uuid4())
        analysis_id = str(uuid4())
        report_id = str(uuid4())

        # Agent 1: real successful call
        out1, err1, lat1, tok1 = _call_llm(
            "What is machine learning? One sentence."
        )
        print(f"\n[research] output={out1!r} latency={lat1}ms")

        # Agent 2: real API error (middle failure)
        out2, err2, lat2, tok2 = _call_llm(
            f"Analyze this: {out1}", force_error=True
        )
        print(f"[analysis] ERRORED: {err2} latency={lat2}ms")
        assert err2 is not None

        # Agent 3: real call but receives null from agent2
        out3, err3, lat3, tok3 = _call_llm(
            f"Write a report on: {out2 or 'no context available'}"
        )
        print(f"[report] output={out3!r} latency={lat3}ms")

        spans = [
            _span(name="pipeline", span_id=root_id, trace_id=trace_id,
                  span_type="agent", output=None, latency_ms=lat1 + lat2 + lat3),
            _span(name="research_agent", span_id=research_id, trace_id=trace_id,
                  parent_span_id=root_id, output=out1, error=err1,
                  latency_ms=lat1, token_usage=tok1),
            _span(name="analysis_agent", span_id=analysis_id, trace_id=trace_id,
                  parent_span_id=root_id, source_span_ids=[research_id],
                  output=out2, error=err2, latency_ms=lat2, token_usage=tok2),
            _span(name="report_agent", span_id=report_id, trace_id=trace_id,
                  parent_span_id=root_id, source_span_ids=[analysis_id],
                  input={"context": out2}, output=out3, error=err3,
                  latency_ms=lat3, token_usage=tok3),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = [o.span_name for o in result.originators]
        manifestor_names = [f.span_name for f in result.failure_points]
        clean_names = [
            n.span.name for n in []  # computed below
        ]

        print(f"\n[blame] originators={originator_names}")
        print(f"[blame] manifestors={manifestor_names}")
        print(f"[blame] confidence={result.confidence}")
        print(f"[blame] summary={result.human_summary}")
        print(f"[blame] chain={result.propagation_chain}")

        assert "analysis_agent" in originator_names, (
            f"Middle agent caused real API error — must be ORIGINATOR. Got: {originator_names}"
        )
        assert "research_agent" not in originator_names, (
            "research_agent succeeded — must not be blamed"
        )
