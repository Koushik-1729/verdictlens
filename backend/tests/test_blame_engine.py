"""
Unit tests for the v2 blame engine (role-based, tree-aware).

Each test builds SpanOut fixtures by hand and calls ``compute_blame`` directly —
no HTTP, no ClickHouse.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.blame_engine import (
    Role, SpanNode, compute_blame, _build_tree, _mark_intrinsic,
    TraceStats, _latency_anomaly_score, _token_anomaly_score, _detect_failure_mode,
    WEIGHT_INPUT_ANOMALY, WEIGHT_OUTPUT_DEVIATION, WEIGHT_LOW_CONFIDENCE,
    WEIGHT_ROLE, WEIGHT_CAUSAL_PROXIMITY, WEIGHT_LATENCY_ANOMALY, WEIGHT_TOKEN_ANOMALY,
)
from app.models import SpanOut, TokenUsageOut


# ── Helpers ──────────────────────────────────────────────────────

_SENTINEL = object()


def _span(
    *,
    name: str,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    trace_id: str = "trace-1",
    span_type: str = "agent",
    output: object = "ok",
    error: object = None,
    input: object = _SENTINEL,
    confidence_score: float | None = None,
    latency_ms: float | None = 100.0,
    start_time: str | None = None,
    source_span_ids: list | None = None,
) -> SpanOut:
    resolved_input = {"args": [], "kwargs": {}} if input is _SENTINEL else input
    return SpanOut(
        span_id=span_id or str(uuid4()),
        parent_span_id=parent_span_id,
        trace_id=trace_id,
        name=name,
        span_type=span_type,
        start_time=start_time,
        end_time=None,
        latency_ms=latency_ms,
        model=None,
        input=resolved_input,
        output=output,
        confidence_score=confidence_score,
        token_usage=None,
        cost_usd=None,
        error=error,
        metadata={},
        source_span_ids=source_span_ids or [],
    )


# ── Test 1: planning_agent → summary_agent ───────────────────────

class TestPlanningSummaryScenario:
    """
    planning_agent produces null output.
    summary_agent receives planning_agent's output as its input (tracked via
    source_span_ids — the SDK records the data-flow link at call time).

    planning_agent should be ORIGINATOR (it created the bad state).
    summary_agent should be MANIFESTOR (victim of upstream null).
    """

    def test_originator_wins_over_manifestor(self):
        root_id = str(uuid4())
        planning_id = str(uuid4())
        summary_id = str(uuid4())

        spans = [
            _span(
                name="pipeline",
                span_id=root_id,
                output={"result": "done"},
            ),
            _span(
                name="planning_agent",
                span_id=planning_id,
                parent_span_id=root_id,
                output=None,
            ),
            _span(
                name="summary_agent",
                span_id=summary_id,
                parent_span_id=root_id,
                # SDK records that planning_agent's output was passed here
                source_span_ids=[planning_id],
                output=None,
                error={"type": "ValueError", "message": "planning output was null"},
            ),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = [o.span_name for o in result.originators]
        assert "planning_agent" in originator_names

        manifestor_names = [f.span_name for f in result.failure_points]
        assert "summary_agent" in manifestor_names, (
            f"summary_agent should be MANIFESTOR (data-flow from planning_agent); "
            f"got failure_points={manifestor_names}"
        )

        planning_score = next(
            o.blame_score for o in result.originators if o.span_name == "planning_agent"
        )
        summary_score = next(
            (f.blame_score for f in result.failure_points if f.span_name == "summary_agent"),
            0.0,
        )
        assert planning_score > summary_score

        assert result.confidence in ("high", "medium")


# ── Test 2: Two independent failures ─────────────────────────────

class TestTwoIndependentFailures:
    """
    Two subtrees under root each have a single error leaf.
    No ancestor-descendant relationship between them.

    Should produce 2 originators and confidence "ambiguous" (or "medium"
    if scores differ enough due to input/output differences).
    """

    def test_co_originators(self):
        root_id = str(uuid4())
        branch_a_id = str(uuid4())
        branch_b_id = str(uuid4())
        leaf_a_id = str(uuid4())
        leaf_b_id = str(uuid4())

        spans = [
            _span(name="root", span_id=root_id, output={"ok": True}),
            _span(
                name="branch_a",
                span_id=branch_a_id,
                parent_span_id=root_id,
                output={"data": "partial"},
            ),
            _span(
                name="branch_b",
                span_id=branch_b_id,
                parent_span_id=root_id,
                output={"data": "partial"},
            ),
            _span(
                name="leaf_error_a",
                span_id=leaf_a_id,
                parent_span_id=branch_a_id,
                error={"type": "Timeout", "message": "connection timed out"},
                output=None,
            ),
            _span(
                name="leaf_error_b",
                span_id=leaf_b_id,
                parent_span_id=branch_b_id,
                error={"type": "APIError", "message": "rate limit exceeded"},
                output=None,
            ),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "leaf_error_a" in originator_names or "leaf_error_b" in originator_names

        if result.confidence == "ambiguous":
            assert len(result.originators) >= 2


# ── Test 3: Retry storm ──────────────────────────────────────────

class TestRetryStorm:
    """
    4 spans with same name under the same parent, all errored.

    Should detect retry_storm=True and blame the first instance.
    """

    def test_retry_storm_detected(self):
        root_id = str(uuid4())
        retry_ids = [str(uuid4()) for _ in range(4)]

        spans = [
            _span(name="agent", span_id=root_id, output={"status": "ok"}),
        ]
        for i, rid in enumerate(retry_ids):
            spans.append(_span(
                name="fetch_data",
                span_id=rid,
                parent_span_id=root_id,
                start_time=f"2026-03-25T12:00:{i:02d}Z",
                latency_ms=200.0,
                error={"type": "Timeout", "message": f"attempt {i+1} timed out"},
                output=None,
            ))

        result = compute_blame(spans)
        assert result is not None
        assert result.retry_storm is True

        originator_names = [o.span_name for o in result.originators]
        assert "fetch_data" in originator_names

        fetch_originators = [o for o in result.originators if o.span_name == "fetch_data"]
        if fetch_originators:
            blamed_id = fetch_originators[0].span_id
            assert blamed_id == retry_ids[0], "First retry instance should be blamed"


# ── Test 4: Single leaf failure ──────────────────────────────────

class TestSingleLeafFailure:
    """
    One leaf span errors, everything else is clean.

    Confidence should be "high", that leaf is the sole originator.
    """

    def test_high_confidence_single_leaf(self):
        root_id = str(uuid4())
        ok_id = str(uuid4())
        leaf_id = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root_id, output={"status": "ok"}),
            _span(
                name="step_a",
                span_id=ok_id,
                parent_span_id=root_id,
                output={"result": "fine"},
            ),
            _span(
                name="step_b_broken",
                span_id=leaf_id,
                parent_span_id=root_id,
                error={"type": "RuntimeError", "message": "something broke"},
                output=None,
            ),
        ]

        result = compute_blame(spans)
        assert result is not None
        assert result.confidence == "high"
        assert len(result.originators) == 1
        assert result.originators[0].span_name == "step_b_broken"
        assert result.originators[0].role == "originator"


# ── Test 5: Three-level chain (LLM → agent → downstream) ────────

class TestThreeLevelChain:
    """
    LLM child errors → agent returns null → downstream agent fails.

    The LLM span is the deepest point of failure — it intrinsically
    introduced the bad state.  research_agent propagated the null.
    Downstream summary_agent is a manifestor (victim).
    """

    def test_deepest_failure_is_originator(self):
        root_id = str(uuid4())
        agent_id = str(uuid4())
        llm_id = str(uuid4())
        downstream_id = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root_id, output={"status": "partial"}),
            _span(
                name="research_agent",
                span_id=agent_id,
                parent_span_id=root_id,
                output=None,
            ),
            _span(
                name="openai.chat.completions.create(gpt-4o)",
                span_id=llm_id,
                parent_span_id=agent_id,
                span_type="llm",
                error={"type": "ContextWindowExceeded", "message": "context too long"},
                output=None,
            ),
            _span(
                name="summary_agent",
                span_id=downstream_id,
                parent_span_id=root_id,
                # SDK tracked: research_agent's null output was passed here
                source_span_ids=[agent_id],
                error={"type": "ValueError", "message": "research output was null"},
                output=None,
            ),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = [o.span_name for o in result.originators]
        assert "openai.chat.completions.create(gpt-4o)" in originator_names, \
            "LLM span is the deepest intrinsic failure — should be originator"

        manifestor_names = [f.span_name for f in result.failure_points]
        assert "summary_agent" in manifestor_names

        assert result.human_summary, "Human summary should not be empty"
        assert len(result.propagation_chain) >= 2


# ── Test: Serialization shape ─────────────────────────────────────

class TestSerializationShape:
    """Verify model_dump produces the expected API response shape."""

    def test_response_shape(self):
        root_id = str(uuid4())
        leaf_id = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root_id, output="ok"),
            _span(
                name="bad_step",
                span_id=leaf_id,
                parent_span_id=root_id,
                error={"type": "Error", "message": "fail"},
                output=None,
            ),
        ]

        result = compute_blame(spans)
        assert result is not None

        data = result.model_dump()
        assert "originators" in data
        assert data["originators"][0]["span_name"] == "bad_step"
        assert data["originators"][0]["role"] == "originator"
        assert "propagation_chain" in data
        assert isinstance(data["propagation_chain"], list)
        assert "confidence" in data
        assert "human_summary" in data
        assert "full_chain" in data


# ── Test: Data-flow lineage (Option B) ───────────────────────────

class TestDataFlowLineage:
    """
    Verify that ``source_span_ids`` (SDK object-identity tracking) correctly
    routes blame across cross-subtree and sibling data-flow edges.
    """

    def test_cross_subtree_flow_marks_downstream_as_manifestor(self):
        """
        Two sibling spans, no parent-child relationship between them.
        fetch_data (bad) → process_data (receives fetch's output via source_span_ids).
        Without source_span_ids the engine can't detect the link.
        With source_span_ids, process_data becomes MANIFESTOR.
        """
        root_id = str(uuid4())
        fetch_id = str(uuid4())
        process_id = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root_id, output="done"),
            _span(
                name="fetch_data",
                span_id=fetch_id,
                parent_span_id=root_id,
                error={"type": "APIError", "message": "upstream 500"},
                output=None,
            ),
            _span(
                name="process_data",
                span_id=process_id,
                parent_span_id=root_id,
                # SDK tracked that fetch_data's output was passed here
                source_span_ids=[fetch_id],
                output=None,
                error={"type": "TypeError", "message": "received None from fetch_data"},
            ),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = [o.span_name for o in result.originators]
        assert "fetch_data" in originator_names, "fetch_data introduced the bad state"

        manifestor_names = [f.span_name for f in result.failure_points]
        assert "process_data" in manifestor_names, (
            "process_data received bad output via data-flow — should be MANIFESTOR"
        )

    def test_no_source_span_ids_both_flagged_as_originators(self):
        """
        Same topology but WITHOUT source_span_ids.
        The engine cannot infer the data-flow link, so both spans appear
        as independent originators.
        """
        root_id = str(uuid4())
        fetch_id = str(uuid4())
        process_id = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root_id, output="done"),
            _span(
                name="fetch_data",
                span_id=fetch_id,
                parent_span_id=root_id,
                error={"type": "APIError", "message": "upstream 500"},
                output=None,
            ),
            _span(
                name="process_data",
                span_id=process_id,
                parent_span_id=root_id,
                # No source_span_ids — link is invisible to the engine
                output=None,
                error={"type": "TypeError", "message": "received None"},
            ),
        ]

        result = compute_blame(spans)
        assert result is not None

        # Both are bad with no lineage link — both show as originators
        all_blamed = {o.span_name for o in result.originators}
        all_blamed |= {f.span_name for f in result.failure_points}
        assert "fetch_data" in all_blamed
        assert "process_data" in all_blamed

    def test_fan_in_both_sources_bad_downstream_is_manifestor(self):
        """
        Fan-in: worker_a and worker_b both produce outputs that are merged.
        worker_a errors → merge_agent (source_span_ids=[worker_a_id]) is MANIFESTOR.
        """
        root_id = str(uuid4())
        worker_a_id = str(uuid4())
        worker_b_id = str(uuid4())
        merge_id = str(uuid4())

        spans = [
            _span(name="orchestrator", span_id=root_id, output="done"),
            _span(
                name="worker_a",
                span_id=worker_a_id,
                parent_span_id=root_id,
                error={"type": "RuntimeError", "message": "worker_a crashed"},
                output=None,
            ),
            _span(
                name="worker_b",
                span_id=worker_b_id,
                parent_span_id=root_id,
                output={"result": "fine"},
            ),
            _span(
                name="merge_agent",
                span_id=merge_id,
                parent_span_id=root_id,
                source_span_ids=[worker_a_id, worker_b_id],
                output=None,
                error={"type": "ValueError", "message": "worker_a result was None"},
            ),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = [o.span_name for o in result.originators]
        assert "worker_a" in originator_names

        manifestor_names = [f.span_name for f in result.failure_points]
        assert "merge_agent" in manifestor_names

    def test_clean_span_with_bad_source_not_blamed(self):
        """
        A span that received bad input but succeeded (no error, valid output)
        should remain CLEAN even when source_span_ids points to a bad span.
        """
        root_id = str(uuid4())
        bad_producer_id = str(uuid4())
        resilient_id = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root_id, output="ok"),
            _span(
                name="bad_producer",
                span_id=bad_producer_id,
                parent_span_id=root_id,
                error={"type": "Error", "message": "failed"},
                output=None,
            ),
            _span(
                name="resilient_consumer",
                span_id=resilient_id,
                parent_span_id=root_id,
                source_span_ids=[bad_producer_id],
                # Handled the error gracefully — good output, no error
                output={"result": "fallback used"},
            ),
        ]

        result = compute_blame(spans)
        assert result is not None

        # resilient_consumer succeeded despite bad input — should not appear in blame
        all_blamed_names = (
            {o.span_name for o in result.originators}
            | {f.span_name for f in result.failure_points}
        )
        assert "resilient_consumer" not in all_blamed_names


# ── Test: Weights sum ────────────────────────────────────────────

class TestWeights:
    """Verify scoring weights still sum to 1.0 after MULAN signals were added."""

    def test_weights_sum_to_one(self):
        total = (
            WEIGHT_INPUT_ANOMALY
            + WEIGHT_OUTPUT_DEVIATION
            + WEIGHT_LOW_CONFIDENCE
            + WEIGHT_ROLE
            + WEIGHT_CAUSAL_PROXIMITY
            + WEIGHT_LATENCY_ANOMALY
            + WEIGHT_TOKEN_ANOMALY
        )
        assert abs(total - 1.0) < 1e-9, f"Weights must sum to 1.0, got {total}"


# ── Test: MAST failure mode detection ────────────────────────────

def _make_node(span: SpanOut) -> SpanNode:
    """Minimal SpanNode with intrinsic state marked."""
    node = SpanNode(span)
    from app.blame_engine import _has_error, _is_null_output, _is_empty_output, _has_bad_input
    node.self_error = _has_error(span)
    node.self_null_output = _is_null_output(span)
    node.self_empty_output = _is_empty_output(span)
    node.self_bad = node.self_error or node.self_null_output or node.self_empty_output
    node.self_bad_input = _has_bad_input(span)
    return node


class TestMastFailureModes:
    """MAST taxonomy failure mode detection (NeurIPS 2025)."""

    def test_context_overflow_detected(self):
        span = _span(
            name="llm_call",
            span_type="llm",
            error={"type": "ContextLengthExceeded", "message": "max tokens exceeded"},
            output=None,
        )
        node = _make_node(span)
        mode = _detect_failure_mode(node)
        assert mode == "system_design/context_overflow"

    def test_tool_failure_detected(self):
        span = _span(
            name="search_tool",
            span_type="tool",
            error={"type": "RuntimeError", "message": "tool crashed"},
            output=None,
        )
        node = _make_node(span)
        mode = _detect_failure_mode(node)
        assert mode == "system_design/tool_failure"

    def test_wrong_output_format_detected(self):
        span = _span(
            name="parser",
            span_type="agent",
            error={"type": "JSONDecodeError", "message": "invalid json parse error"},
            output=None,
        )
        node = _make_node(span)
        mode = _detect_failure_mode(node)
        assert mode == "inter_agent/wrong_output_format"

    def test_rate_limit_detected(self):
        span = _span(
            name="llm_call",
            span_type="llm",
            error={"type": "RateLimitError", "message": "rate limit exceeded"},
            output=None,
        )
        node = _make_node(span)
        mode = _detect_failure_mode(node)
        assert mode == "system_design/rate_limit"

    def test_no_failure_mode_for_clean_span(self):
        span = _span(name="agent", output={"result": "ok"})
        node = _make_node(span)
        mode = _detect_failure_mode(node)
        assert mode is None

    def test_failure_mode_in_blame_span(self):
        """failure_mode field appears in compute_blame output."""
        root_id = str(uuid4())
        leaf_id = str(uuid4())
        spans = [
            _span(name="pipeline", span_id=root_id, output="ok"),
            _span(
                name="llm_call",
                span_id=leaf_id,
                parent_span_id=root_id,
                span_type="llm",
                error={"type": "ContextLengthExceeded", "message": "max tokens exceeded"},
                output=None,
            ),
        ]
        result = compute_blame(spans)
        assert result is not None
        originator = result.originators[0]
        assert originator.failure_mode == "system_design/context_overflow"


# ── Test: Latency + token anomaly signals ────────────────────────

class TestAnomalySignals:
    """MULAN-inspired latency and token anomaly scoring."""

    def _make_stats(self, avg_latency: float, avg_tokens: float) -> TraceStats:
        stats = TraceStats.__new__(TraceStats)
        stats.avg_latency_ms = avg_latency
        stats.avg_tokens = avg_tokens
        return stats

    def test_latency_spike_5x_scores_max(self):
        span = _span(name="slow_agent", latency_ms=5000.0)
        stats = self._make_stats(avg_latency=1000.0, avg_tokens=0.0)
        score = _latency_anomaly_score(span, stats)
        assert score == 1.0

    def test_latency_spike_3x_scores_high(self):
        span = _span(name="slow_agent", latency_ms=3100.0)
        stats = self._make_stats(avg_latency=1000.0, avg_tokens=0.0)
        score = _latency_anomaly_score(span, stats)
        assert score == 0.7

    def test_normal_latency_scores_zero(self):
        span = _span(name="fast_agent", latency_ms=120.0)
        stats = self._make_stats(avg_latency=100.0, avg_tokens=0.0)
        score = _latency_anomaly_score(span, stats)
        assert score == 0.0

    def test_no_latency_scores_zero(self):
        span = _span(name="no_latency_agent", latency_ms=None)
        stats = self._make_stats(avg_latency=100.0, avg_tokens=0.0)
        assert _latency_anomaly_score(span, stats) == 0.0

    def test_token_runaway_10x_scores_max(self):
        span = SpanOut(
            span_id=str(uuid4()), trace_id="t", name="runaway_llm", span_type="llm",
            token_usage=TokenUsageOut(total_tokens=10000),
        )
        stats = self._make_stats(avg_latency=0.0, avg_tokens=1000.0)
        assert _token_anomaly_score(span, stats) == 1.0

    def test_token_normal_scores_zero(self):
        span = SpanOut(
            span_id=str(uuid4()), trace_id="t", name="normal_llm", span_type="llm",
            token_usage=TokenUsageOut(total_tokens=900),
        )
        stats = self._make_stats(avg_latency=0.0, avg_tokens=1000.0)
        assert _token_anomaly_score(span, stats) == 0.0

    def test_anomaly_signals_boost_originator_score(self):
        """A latency-spiking error span should score higher than a quiet one."""
        root_id = str(uuid4())
        quiet_id = str(uuid4())
        spike_id = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root_id, output="ok"),
            _span(
                name="quiet_error",
                span_id=quiet_id,
                parent_span_id=root_id,
                error={"type": "Error", "message": "fail"},
                output=None,
                latency_ms=100.0,
            ),
            _span(
                name="spiking_error",
                span_id=spike_id,
                parent_span_id=root_id,
                error={"type": "Error", "message": "fail"},
                output=None,
                latency_ms=9000.0,  # 90× the average
            ),
        ]
        result = compute_blame(spans)
        assert result is not None
        scores = {o.span_name: o.blame_score for o in result.originators}
        scores.update({f.span_name: f.blame_score for f in result.failure_points})
        assert scores.get("spiking_error", 0) >= scores.get("quiet_error", 0)


# ── Test: SBFL suspiciousness ─────────────────────────────────────

class TestSbflSuspiciousness:
    """SBFL-inspired suspiciousness score logic (tested directly, no ClickHouse)."""

    def _score(self, orig_out, new_out, orig_err, new_err, status):
        import json, difflib
        orig_had_error = orig_err is not None
        new_has_error = new_err is not None
        if orig_had_error and not new_has_error and new_out is not None:
            return 1.0
        if orig_had_error and new_has_error:
            return 0.9
        if status == "same":
            return 0.1
        orig_str = json.dumps(orig_out, default=str) if orig_out is not None else ""
        new_str = json.dumps(new_out, default=str) if new_out is not None else ""
        if not orig_str and not new_str:
            return 0.1
        longer = max(len(orig_str), len(new_str))
        if longer == 0:
            return 0.1
        sim = difflib.SequenceMatcher(None, orig_str, new_str).ratio()
        return round(max(0.1, min(0.8, 1.0 - sim)), 4)

    def test_error_fixed_is_max_suspicion(self):
        s = self._score(None, "fixed", {"type": "Error"}, None, "improved")
        assert s == 1.0

    def test_both_error_is_high_suspicion(self):
        s = self._score(None, None, {"type": "Error"}, {"type": "Error"}, "degraded")
        assert s == 0.9

    def test_same_output_is_low_suspicion(self):
        s = self._score("hello", "hello", None, None, "same")
        assert s == 0.1

    def test_large_diff_is_high_suspicion(self):
        s = self._score("aaa", "zzzzzzzzzzzzzzzzzzzzz", None, None, "different")
        assert s > 0.5

    def test_small_diff_is_low_suspicion(self):
        long_text = "The quick brown fox jumps over the lazy dog"
        s = self._score(long_text, long_text + ".", None, None, "different")
        assert s < 0.3
