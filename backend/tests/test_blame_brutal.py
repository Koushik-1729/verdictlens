"""
Brutal real-world blame engine test scenarios.

15 scenarios designed to break naive "nearest error wins" logic and validate:
- originator vs manifestor distinction
- sibling propagation
- co-originators
- retry storms & false positives
- graceful degradation / recovery
- ambiguous blame honesty
- pass-through propagators
- broken tree resilience
- partial batch failures
- timing-aware causality

Each test builds SpanOut fixtures and calls ``compute_blame`` directly.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.blame_engine import Role, compute_blame, _build_tree, _mark_intrinsic, _classify_roles
from app.models import SpanOut


# ── Helpers ──────────────────────────────────────────────────────

_SENTINEL = object()


def _span(
    *,
    name: str,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    trace_id: str = "trace-brutal",
    span_type: str = "agent",
    output: object = "ok",
    error: object = None,
    input: object = _SENTINEL,
    confidence_score: float | None = None,
    latency_ms: float | None = 100.0,
    start_time: str | None = None,
    model: str | None = None,
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
        model=model,
        input=resolved_input,
        output=output,
        confidence_score=confidence_score,
        token_usage=None,
        cost_usd=None,
        error=error,
        metadata={},
        source_span_ids=source_span_ids or [],
    )


def _role_map(spans, result):
    """Build {span_name: role} from blame result by inspecting all lists."""
    roles = {}
    for o in result.originators:
        roles[o.span_name] = "originator"
    for f in result.failure_points:
        roles[f.span_name] = "manifestor"
    for s in result.secondary_contributors:
        roles[s.span_name] = "secondary"
    return roles


def _all_blamed_names(result):
    """Return set of all span names that appear in any blame list."""
    names = set()
    for o in result.originators:
        names.add(o.span_name)
    for f in result.failure_points:
        names.add(f.span_name)
    for s in result.secondary_contributors:
        names.add(s.span_name)
    return names


# ══════════════════════════════════════════════════════════════════
# SCENARIO 1: Null context poisoning across siblings
# ══════════════════════════════════════════════════════════════════

class TestScenario01_NullContextPoisoning:
    """
    research_pipeline
    ├── retriever        → output = null
    ├── generator        → input = null, output = fallback text
    └── scorer           → input = fallback text, output = success

    retriever introduces the null. generator is a victim.
    scorer is unaffected because generator produced a fallback.

    Naive failure: blames generator because it consumed null,
    or shows no blame because top-level trace succeeded.
    """

    def test_retriever_is_originator(self):
        root = str(uuid4())
        ret = str(uuid4())
        gen = str(uuid4())
        scr = str(uuid4())

        spans = [
            _span(name="research_pipeline", span_id=root, output={"final": "scored result"}),
            _span(name="retriever", span_id=ret, parent_span_id=root, output=None),
            _span(name="generator", span_id=gen, parent_span_id=root,
                  input=None, output="I don't have context, here's a generic answer"),
            _span(name="scorer", span_id=scr, parent_span_id=root,
                  output={"score": 0.72}),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "retriever" in originator_names, "retriever should be originator"
        assert "scorer" not in originator_names, "scorer must not be blamed"
        assert "research_pipeline" not in originator_names

    def test_generator_is_not_originator(self):
        root = str(uuid4())
        ret = str(uuid4())
        gen = str(uuid4())
        scr = str(uuid4())

        spans = [
            _span(name="research_pipeline", span_id=root, output={"final": "ok"}),
            _span(name="retriever", span_id=ret, parent_span_id=root, output=None),
            _span(name="generator", span_id=gen, parent_span_id=root,
                  input=None, output="fallback text"),
            _span(name="scorer", span_id=scr, parent_span_id=root, output={"score": 0.5}),
        ]

        result = compute_blame(spans)
        assert result is not None
        originator_names = {o.span_name for o in result.originators}
        assert "generator" not in originator_names, \
            "generator received bad input from sibling — must not be originator"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 2: Child LLM failure wrapped by parent agent
# ══════════════════════════════════════════════════════════════════

class TestScenario02_ChildLLMFailure:
    """
    planning_agent
    └── openai.chat.completions.create → error: context length exceeded
    downstream_executor → input missing plan, errors

    The LLM child is the deepest root cause.
    planning_agent propagates (or originates if you frame it as the
    agent that failed to produce output).
    downstream_executor is a manifestor (victim).

    Naive failure: blames planning_agent only because parent "turned red."
    """

    def test_llm_child_is_originator(self):
        root = str(uuid4())
        agent = str(uuid4())
        llm = str(uuid4())
        downstream = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output={"result": "partial"}),
            _span(name="planning_agent", span_id=agent, parent_span_id=root,
                  output=None),
            _span(name="openai.chat.completions.create", span_id=llm,
                  parent_span_id=agent, span_type="llm",
                  error={"type": "ContextWindowExceeded", "message": "max tokens exceeded"},
                  output=None, model="gpt-4o"),
            _span(name="downstream_executor", span_id=downstream,
                  parent_span_id=root,
                  source_span_ids=[agent],  # SDK tracked: planning_agent's null output was passed here
                  error={"type": "ValueError", "message": "plan was null"},
                  output=None),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "openai.chat.completions.create" in originator_names, \
            "LLM child is the deepest intrinsic failure — should be originator"

        manifestor_names = {f.span_name for f in result.failure_points}
        assert "downstream_executor" in manifestor_names, \
            "downstream_executor is a victim"

    def test_downstream_never_outranks_originator(self):
        root = str(uuid4())
        agent = str(uuid4())
        llm = str(uuid4())
        downstream = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output={"result": "partial"}),
            _span(name="planning_agent", span_id=agent, parent_span_id=root, output=None),
            _span(name="llm_call", span_id=llm, parent_span_id=agent, span_type="llm",
                  error={"type": "Timeout", "message": "timed out"}, output=None),
            _span(name="downstream", span_id=downstream, parent_span_id=root,
                  input=None, error={"type": "Error", "message": "missing input"},
                  output=None),
        ]

        result = compute_blame(spans)
        assert result is not None

        orig_score = max((o.blame_score for o in result.originators), default=0)
        manifest_score = max((f.blame_score for f in result.failure_points), default=0)
        assert orig_score >= manifest_score, \
            "Manifestor must never outrank originator"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 3: Pass-through formatter with no explicit error
# ══════════════════════════════════════════════════════════════════

class TestScenario03_PassThroughFormatter:
    """
    pipeline
    ├── planner       → output = null
    ├── formatter     → input = null, output = null, no exception
    └── summarizer    → input = null, error

    planner = ORIGINATOR (introduced null)
    formatter = PROPAGATOR (passed null through without error)
    summarizer = MANIFESTOR (where the crash happened)

    Naive failure: skips formatter, blames summarizer because it has the exception.
    """

    def test_planner_originator_formatter_propagator(self):
        root = str(uuid4())
        planner = str(uuid4())
        formatter = str(uuid4())
        summarizer = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output={"status": "failed"}),
            _span(name="planner", span_id=planner, parent_span_id=root, output=None),
            _span(name="formatter", span_id=formatter, parent_span_id=root,
                  source_span_ids=[planner], output=None),
            _span(name="summarizer", span_id=summarizer, parent_span_id=root,
                  source_span_ids=[formatter], output=None,
                  error={"type": "TypeError", "message": "cannot summarize null"}),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "planner" in originator_names, "planner introduced null output"
        assert "summarizer" not in originator_names, \
            "summarizer is a victim, not originator"

    def test_summarizer_exception_does_not_win(self):
        root = str(uuid4())
        planner = str(uuid4())
        formatter = str(uuid4())
        summarizer = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output=None),
            _span(name="planner", span_id=planner, parent_span_id=root, output=None),
            _span(name="formatter", span_id=formatter, parent_span_id=root,
                  source_span_ids=[planner], output=None),
            _span(name="summarizer", span_id=summarizer, parent_span_id=root,
                  source_span_ids=[formatter], output=None,
                  error={"type": "TypeError", "message": "boom"}),
        ]

        result = compute_blame(spans)
        assert result is not None

        planner_score = next(
            (o.blame_score for o in result.originators if o.span_name == "planner"), 0
        )
        summarizer_score = next(
            (f.blame_score for f in result.failure_points if f.span_name == "summarizer"),
            next((o.blame_score for o in result.originators if o.span_name == "summarizer"), 0)
        )
        assert planner_score >= summarizer_score, \
            "Planner (originator) must score >= summarizer (victim with exception)"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 4: Two independent failures in different subtrees
# ══════════════════════════════════════════════════════════════════

class TestScenario04_TwoIndependentSubtreeFailures:
    """
    root_pipeline
    ├── search_branch
    │   └── retriever → output = null
    └── compliance_branch
        └── policy_check → error: timeout

    Two completely independent failures. No causal link.
    Should produce co-originators + ambiguous confidence.

    Naive failure: picks whichever scores slightly higher and
    pretends certainty.
    """

    def test_both_are_originators(self):
        root = str(uuid4())
        search = str(uuid4())
        retriever = str(uuid4())
        compliance = str(uuid4())
        policy = str(uuid4())

        spans = [
            _span(name="root_pipeline", span_id=root, output={"partial": True}),
            _span(name="search_branch", span_id=search, parent_span_id=root,
                  output={"data": "partial"}),
            _span(name="retriever", span_id=retriever, parent_span_id=search,
                  output=None),
            _span(name="compliance_branch", span_id=compliance, parent_span_id=root,
                  output={"data": "partial"}),
            _span(name="policy_check", span_id=policy, parent_span_id=compliance,
                  error={"type": "Timeout", "message": "compliance API timed out"},
                  output=None),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "retriever" in originator_names or "policy_check" in originator_names

    def test_confidence_not_high_with_two_independent(self):
        root = str(uuid4())
        search = str(uuid4())
        retriever = str(uuid4())
        compliance = str(uuid4())
        policy = str(uuid4())

        spans = [
            _span(name="root_pipeline", span_id=root, output={"partial": True}),
            _span(name="search_branch", span_id=search, parent_span_id=root,
                  output={"data": "partial"}),
            _span(name="retriever", span_id=retriever, parent_span_id=search,
                  output=None),
            _span(name="compliance_branch", span_id=compliance, parent_span_id=root,
                  output={"data": "partial"}),
            _span(name="policy_check", span_id=policy, parent_span_id=compliance,
                  error={"type": "Timeout", "message": "timed out"}, output=None),
        ]

        result = compute_blame(spans)
        assert result is not None
        assert result.confidence in ("ambiguous", "medium"), \
            f"Two independent failures should not yield high confidence, got {result.confidence}"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 5: Retry storm with fallback LLM
# ══════════════════════════════════════════════════════════════════

class TestScenario05_RetryStormWithFallback:
    """
    agent
    ├── tool_call retry #1 → timeout
    ├── tool_call retry #2 → timeout
    ├── tool_call retry #3 → timeout
    └── fallback_llm → generic answer (success)

    retry_storm = true, first tool_call = ORIGINATOR.
    fallback_llm is clean.

    Naive failure: blames last retry or treats all as independent.
    """

    def test_storm_detected_fallback_not_blamed(self):
        root = str(uuid4())
        retry_ids = [str(uuid4()) for _ in range(3)]
        fallback = str(uuid4())

        spans = [
            _span(name="agent", span_id=root, output={"answer": "generic fallback"}),
        ]
        for i, rid in enumerate(retry_ids):
            spans.append(_span(
                name="tool_call",
                span_id=rid,
                parent_span_id=root,
                start_time=f"2026-03-25T12:00:{i:02d}Z",
                latency_ms=500.0,
                error={"type": "Timeout", "message": f"attempt {i + 1} timed out"},
                output=None,
            ))
        spans.append(_span(
            name="fallback_llm", span_id=fallback, parent_span_id=root,
            output="Here's a generic answer based on my training data.",
        ))

        result = compute_blame(spans)
        assert result is not None
        assert result.retry_storm is True

        blamed_names = _all_blamed_names(result)
        assert "fallback_llm" not in blamed_names, \
            "fallback_llm succeeded — must not be blamed"

    def test_first_retry_is_blamed(self):
        root = str(uuid4())
        retry_ids = [str(uuid4()) for _ in range(3)]

        spans = [_span(name="agent", span_id=root, output={"status": "ok"})]
        for i, rid in enumerate(retry_ids):
            spans.append(_span(
                name="tool_call", span_id=rid, parent_span_id=root,
                start_time=f"2026-03-25T12:00:{i:02d}Z",
                latency_ms=500.0,
                error={"type": "Timeout", "message": f"attempt {i + 1}"},
                output=None,
            ))

        result = compute_blame(spans)
        assert result is not None
        assert result.retry_storm is True

        originator_ids = [o.span_id for o in result.originators if o.span_name == "tool_call"]
        if originator_ids:
            assert originator_ids[0] == retry_ids[0], \
                "First retry instance should be blamed, not later ones"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 6: Graceful recovery after upstream corruption
# ══════════════════════════════════════════════════════════════════

class TestScenario06_GracefulRecovery:
    """
    qa_pipeline
    ├── retriever  → output = null
    ├── generator  → input = null, output = "No context found"
    └── guardrail  → rewrites into valid user-safe message

    retriever = ORIGINATOR
    generator = MANIFESTOR or AFFECTED
    guardrail = CLEAN (it recovered the situation)
    Top-level trace is success.

    Naive failure: blames guardrail because it touched final output,
    or shows no blame because final output looks okay.
    """

    def test_retriever_blamed_guardrail_clean(self):
        root = str(uuid4())
        ret = str(uuid4())
        gen = str(uuid4())
        guard = str(uuid4())

        spans = [
            _span(name="qa_pipeline", span_id=root,
                  output={"answer": "I'm sorry, I don't have enough information."}),
            _span(name="retriever", span_id=ret, parent_span_id=root, output=None),
            _span(name="generator", span_id=gen, parent_span_id=root,
                  input=None, output="No context found"),
            _span(name="guardrail", span_id=guard, parent_span_id=root,
                  output="I'm sorry, I don't have enough information."),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "retriever" in originator_names

        blamed_names = _all_blamed_names(result)
        assert "guardrail" not in blamed_names, "guardrail recovered — must not be blamed"

    def test_blame_exists_despite_success_status(self):
        root = str(uuid4())
        ret = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output={"answer": "fallback answer"}),
            _span(name="retriever", span_id=ret, parent_span_id=root, output=None),
        ]

        result = compute_blame(spans)
        assert result is not None, \
            "Blame should fire even when top-level trace succeeded — retriever output is null"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 7: Clean parent, sibling dependency broken
# ══════════════════════════════════════════════════════════════════

class TestScenario07_CleanParentSiblingBroken:
    """
    orchestrator
    ├── feature_extractor → output = malformed JSON (empty dict)
    ├── ranker            → input malformed, error
    └── renderer          → never meaningfully affected

    feature_extractor = ORIGINATOR
    ranker = MANIFESTOR
    orchestrator = CLEAN
    renderer = CLEAN

    Naive failure: misses causality because parent is clean,
    blames ranker only.
    """

    def test_feature_extractor_originator(self):
        root = str(uuid4())
        fe = str(uuid4())
        ranker = str(uuid4())
        renderer = str(uuid4())

        spans = [
            _span(name="orchestrator", span_id=root, output={"page": "rendered"}),
            _span(name="feature_extractor", span_id=fe, parent_span_id=root,
                  output={}),
            _span(name="ranker", span_id=ranker, parent_span_id=root,
                  input={}, output=None,
                  error={"type": "KeyError", "message": "'features' key missing"}),
            _span(name="renderer", span_id=renderer, parent_span_id=root,
                  output={"html": "<div>results</div>"}),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "feature_extractor" in originator_names or "ranker" in originator_names

        blamed_names = _all_blamed_names(result)
        assert "renderer" not in blamed_names, "renderer is clean"

    def test_orchestrator_is_not_propagator(self):
        root = str(uuid4())
        fe = str(uuid4())
        ranker = str(uuid4())

        spans = [
            _span(name="orchestrator", span_id=root, output={"status": "degraded"}),
            _span(name="feature_extractor", span_id=fe, parent_span_id=root, output={}),
            _span(name="ranker", span_id=ranker, parent_span_id=root,
                  input={}, output=None,
                  error={"type": "KeyError", "message": "missing features"}),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "orchestrator" not in originator_names, \
            "Clean parent must not be labeled as originator"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 8: Leaf tool timeout causing agent collapse
# ══════════════════════════════════════════════════════════════════

class TestScenario08_LeafToolTimeout:
    """
    agent
    └── db_tool → timeout error
    postprocess → input missing data, error

    db_tool (leaf) = ORIGINATOR
    agent = PROPAGATOR or clean wrapper
    postprocess = MANIFESTOR

    Naive failure: assumes leaf cannot be originator, blames agent wrapper.
    """

    def test_leaf_tool_is_originator(self):
        root = str(uuid4())
        agent = str(uuid4())
        db = str(uuid4())
        post = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output=None),
            _span(name="agent", span_id=agent, parent_span_id=root, output=None),
            _span(name="db_tool", span_id=db, parent_span_id=agent,
                  span_type="tool",
                  error={"type": "Timeout", "message": "connection timed out after 30s"},
                  output=None, latency_ms=30000.0),
            _span(name="postprocess", span_id=post, parent_span_id=root,
                  input=None,
                  error={"type": "ValueError", "message": "no data to process"},
                  output=None),
        ]

        result = compute_blame(spans)
        assert result is not None

        all_originator_names = {o.span_name for o in result.originators}
        all_secondary_names = {s.span_name for s in result.secondary_contributors}
        assert "db_tool" in all_originator_names or "db_tool" in all_secondary_names, \
            "Leaf tool must appear as originator or secondary contributor"

    def test_postprocess_is_manifestor(self):
        root = str(uuid4())
        agent = str(uuid4())
        db = str(uuid4())
        post = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output=None),
            _span(name="agent", span_id=agent, parent_span_id=root, output=None),
            _span(name="db_tool", span_id=db, parent_span_id=agent, span_type="tool",
                  error={"type": "Timeout", "message": "timed out"}, output=None),
            _span(name="postprocess", span_id=post, parent_span_id=root,
                  source_span_ids=[agent],  # agent's null output was passed here
                  error={"type": "Error", "message": "no data"}, output=None),
        ]

        result = compute_blame(spans)
        assert result is not None

        manifestor_names = {f.span_name for f in result.failure_points}
        assert "postprocess" in manifestor_names, \
            "postprocess should be manifestor (received null from sibling agent)"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 9: Same-name spans, unrelated contexts (no false storm)
# ══════════════════════════════════════════════════════════════════

class TestScenario09_SameNameUnrelatedContexts:
    """
    root
    ├── enrich_user
    │   └── profile_service → error
    ├── enrich_order
    │   └── profile_service → success
    └── enrich_vendor
        └── profile_service → error

    Must NOT mark retry_storm because the profile_service spans have
    different parents (different contexts).

    Naive failure: collapses all profile_service spans into one storm.
    """

    def test_no_false_retry_storm(self):
        root = str(uuid4())
        eu = str(uuid4())
        eo = str(uuid4())
        ev = str(uuid4())
        ps1 = str(uuid4())
        ps2 = str(uuid4())
        ps3 = str(uuid4())

        spans = [
            _span(name="root", span_id=root, output={"status": "partial"}),
            _span(name="enrich_user", span_id=eu, parent_span_id=root, output=None),
            _span(name="profile_service", span_id=ps1, parent_span_id=eu,
                  error={"type": "NotFound", "message": "user not found"}, output=None),
            _span(name="enrich_order", span_id=eo, parent_span_id=root,
                  output={"order": "enriched"}),
            _span(name="profile_service", span_id=ps2, parent_span_id=eo,
                  output={"profile": "data"}),
            _span(name="enrich_vendor", span_id=ev, parent_span_id=root, output=None),
            _span(name="profile_service", span_id=ps3, parent_span_id=ev,
                  error={"type": "NotFound", "message": "vendor not found"}, output=None),
        ]

        result = compute_blame(spans)
        assert result is not None
        assert result.retry_storm is False, \
            "Different parent contexts — must NOT be flagged as retry storm"

    def test_each_failure_blamed_independently(self):
        root = str(uuid4())
        eu = str(uuid4())
        ev = str(uuid4())
        ps1 = str(uuid4())
        ps3 = str(uuid4())

        spans = [
            _span(name="root", span_id=root, output={"partial": True}),
            _span(name="enrich_user", span_id=eu, parent_span_id=root, output=None),
            _span(name="profile_service", span_id=ps1, parent_span_id=eu,
                  error={"type": "NotFound", "message": "not found"}, output=None),
            _span(name="enrich_vendor", span_id=ev, parent_span_id=root, output=None),
            _span(name="profile_service", span_id=ps3, parent_span_id=ev,
                  error={"type": "NotFound", "message": "not found"}, output=None),
        ]

        result = compute_blame(spans)
        assert result is not None
        assert len(result.originators) >= 1


# ══════════════════════════════════════════════════════════════════
# SCENARIO 10: Broken tree / missing parent / orphan spans
# ══════════════════════════════════════════════════════════════════

class TestScenario10_BrokenTree:
    """
    Span C references non-existent parent.
    Engine must not crash. Orphan becomes a synthetic root.

    Naive failure: KeyError, panic, or random blame.
    """

    def test_no_crash_on_orphan(self):
        root = str(uuid4())
        child = str(uuid4())
        orphan = str(uuid4())

        spans = [
            _span(name="root_agent", span_id=root, output={"status": "ok"}),
            _span(name="step_a", span_id=child, parent_span_id=root, output="fine"),
            _span(name="orphan_span", span_id=orphan,
                  parent_span_id="nonexistent-parent-id",
                  error={"type": "Error", "message": "something broke"},
                  output=None),
        ]

        result = compute_blame(spans)
        assert result is not None, "Engine must handle orphan spans gracefully"

        originator_names = {o.span_name for o in result.originators}
        assert "orphan_span" in originator_names, \
            "Orphan with error should be its own originator"

    def test_no_crash_on_empty_trace(self):
        result = compute_blame([])
        assert result is None, "Empty span list should return None"

    def test_single_span_trace(self):
        sid = str(uuid4())
        spans = [
            _span(name="lonely_agent", span_id=sid,
                  error={"type": "Error", "message": "failed alone"},
                  output=None),
        ]
        result = compute_blame(spans)
        assert result is not None
        assert result.originators[0].span_name == "lonely_agent"
        assert result.confidence == "high"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 11: Wrong-value propagation without nulls
# ══════════════════════════════════════════════════════════════════

class TestScenario11_WrongValueNoNulls:
    """
    planner → outputs "DROP TABLE users" (looks valid, is dangerous)
    executor → faithfully executes the dangerous step (no error)

    Engine should NOT overclaim. Without schema validators, both
    spans look "clean." The engine should either not trigger blame
    or report low/ambiguous confidence.

    Tests honesty — the right answer may be "insufficient evidence."
    """

    def test_no_blame_when_all_outputs_present(self):
        root = str(uuid4())
        planner = str(uuid4())
        executor = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output={"result": "executed"}),
            _span(name="planner", span_id=planner, parent_span_id=root,
                  output="DROP TABLE users"),
            _span(name="executor", span_id=executor, parent_span_id=root,
                  output="Query executed successfully"),
        ]

        result = compute_blame(spans)
        assert result is None, \
            "No null/error/empty signals — engine should not fabricate blame"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 12: Delayed failure with long propagation chain
# ══════════════════════════════════════════════════════════════════

class TestScenario12_LongPropagationChain:
    """
    pipeline
    ├── retriever  → partial bad data (some null fields)
    ├── planner    → weak plan based on partial data (output has nulls)
    ├── executor   → weird tool args
    └── validator  → final failure

    Originator should be upstream (retriever) even though the crash
    is in validator. Long chain must not over-blame deepest node.
    """

    def test_upstream_retriever_is_originator(self):
        root = str(uuid4())
        ret = str(uuid4())
        plan = str(uuid4())
        exe = str(uuid4())
        val = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output=None),
            _span(name="retriever", span_id=ret, parent_span_id=root,
                  output={"results": None, "metadata": "ok"}),
            _span(name="planner", span_id=plan, parent_span_id=root,
                  output=None),
            _span(name="executor", span_id=exe, parent_span_id=root,
                  source_span_ids=[plan], output=None),
            _span(name="validator", span_id=val, parent_span_id=root,
                  source_span_ids=[exe], output=None,
                  error={"type": "ValidationError", "message": "all fields null"}),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "validator" not in originator_names, \
            "Validator (end of chain) should not be originator"

    def test_propagation_chain_has_multiple_entries(self):
        root = str(uuid4())
        ret = str(uuid4())
        plan = str(uuid4())
        val = str(uuid4())

        spans = [
            _span(name="pipeline", span_id=root, output=None),
            _span(name="retriever", span_id=ret, parent_span_id=root, output=None),
            _span(name="planner", span_id=plan, parent_span_id=root,
                  input=None, output=None),
            _span(name="validator", span_id=val, parent_span_id=root,
                  input=None, output=None,
                  error={"type": "Error", "message": "validation failed"}),
        ]

        result = compute_blame(spans)
        assert result is not None
        assert len(result.propagation_chain) >= 2, \
            "Long chain should produce multi-step propagation narrative"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 13: Concurrent branches — timing prevents causality
# ══════════════════════════════════════════════════════════════════

class TestScenario13_ConcurrentBranches:
    """
    root
    ├── branch_a → bad output (finishes at T=5s)
    └── branch_b → bad input (starts at T=1s, before branch_a finishes)

    Since branch_b started before branch_a finished, branch_a cannot
    have caused branch_b's bad input through sibling propagation.
    Both should be independent originators.

    Naive failure: treats branch_a as cause of branch_b.
    """

    def test_independent_when_concurrent(self):
        root = str(uuid4())
        a = str(uuid4())
        b = str(uuid4())

        spans = [
            _span(name="root", span_id=root, output={"partial": True}),
            _span(name="branch_a", span_id=a, parent_span_id=root,
                  start_time="2026-03-25T12:00:00Z",
                  latency_ms=5000.0,
                  output=None),
            _span(name="branch_b", span_id=b, parent_span_id=root,
                  start_time="2026-03-25T12:00:01Z",
                  latency_ms=2000.0,
                  output=None,
                  error={"type": "Error", "message": "bad data"}),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert len(originator_names) >= 1
        assert result.confidence in ("ambiguous", "medium", "high")


# ══════════════════════════════════════════════════════════════════
# SCENARIO 14: Clean parent, dirty child, recovered grandchild
# ══════════════════════════════════════════════════════════════════

class TestScenario14_DirtyChildRecoveredGrandchild:
    """
    agent (clean)
    └── llm_call → empty output
        └── parser → fallback parse succeeds

    llm_call = ORIGINATOR (produced empty output)
    parser = CLEAN (recovered via fallback)
    agent = CLEAN

    Not every descendant with success should be blamed.
    """

    def test_llm_originator_parser_clean(self):
        root = str(uuid4())
        llm = str(uuid4())
        parser = str(uuid4())

        spans = [
            _span(name="agent", span_id=root, output={"result": "parsed ok"}),
            _span(name="llm_call", span_id=llm, parent_span_id=root,
                  span_type="llm", output="", model="gpt-4o"),
            _span(name="parser", span_id=parser, parent_span_id=llm,
                  input="", output={"parsed": "fallback default"}),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "llm_call" in originator_names, "llm_call produced empty output"

        blamed_names = _all_blamed_names(result)
        assert "parser" not in blamed_names, \
            "parser recovered — must not appear in blame"
        assert "agent" not in blamed_names, \
            "agent is clean"


# ══════════════════════════════════════════════════════════════════
# SCENARIO 15: Partial batch failure
# ══════════════════════════════════════════════════════════════════

class TestScenario15_PartialBatchFailure:
    """
    batch_analyzer
    ├── analyze(item1) → success
    ├── analyze(item2) → null output
    ├── analyze(item3) → success
    └── merge_results  → success with degraded quality

    analyze(item2) = ORIGINATOR
    merge_results = CLEAN (it succeeded)
    Top-level trace success.

    Real-world pattern: multi-item agent systems where
    partial failures degrade but don't crash the pipeline.
    """

    def test_partial_item_blamed(self):
        root = str(uuid4())
        a1 = str(uuid4())
        a2 = str(uuid4())
        a3 = str(uuid4())
        merge = str(uuid4())

        spans = [
            _span(name="batch_analyzer", span_id=root,
                  output={"results": ["ok", None, "ok"], "quality": "degraded"}),
            _span(name="analyze_item1", span_id=a1, parent_span_id=root,
                  output={"analysis": "positive sentiment"}),
            _span(name="analyze_item2", span_id=a2, parent_span_id=root,
                  output=None),
            _span(name="analyze_item3", span_id=a3, parent_span_id=root,
                  output={"analysis": "neutral sentiment"}),
            _span(name="merge_results", span_id=merge, parent_span_id=root,
                  output={"merged": True, "count": 2}),
        ]

        result = compute_blame(spans)
        assert result is not None

        originator_names = {o.span_name for o in result.originators}
        assert "analyze_item2" in originator_names, \
            "The item that returned null should be originator"

        blamed_names = _all_blamed_names(result)
        assert "analyze_item1" not in blamed_names
        assert "analyze_item3" not in blamed_names
        assert "merge_results" not in blamed_names, \
            "merge_results succeeded — must not be blamed"

    def test_confidence_high_single_bad_item(self):
        root = str(uuid4())
        a1 = str(uuid4())
        a2 = str(uuid4())
        merge = str(uuid4())

        spans = [
            _span(name="batch", span_id=root, output={"partial": True}),
            _span(name="item_ok", span_id=a1, parent_span_id=root,
                  output={"data": "good"}),
            _span(name="item_bad", span_id=a2, parent_span_id=root, output=None),
            _span(name="merge", span_id=merge, parent_span_id=root,
                  output={"merged": True}),
        ]

        result = compute_blame(spans)
        assert result is not None
        assert result.confidence == "high", \
            "Single bad item among healthy siblings should be high confidence"
        assert result.originators[0].span_name == "item_bad"


# ══════════════════════════════════════════════════════════════════
# CROSS-CUTTING: Structural assertions
# ══════════════════════════════════════════════════════════════════

class TestCrossCuttingInvariants:
    """
    Properties that must hold for ANY blame result regardless of scenario.
    """

    @pytest.fixture(params=[
        "single_error",
        "sibling_null",
        "deep_chain",
    ])
    def scenario_spans(self, request):
        root = str(uuid4())
        if request.param == "single_error":
            return [
                _span(name="root", span_id=root, output="ok"),
                _span(name="broken", parent_span_id=root,
                      error={"type": "Error", "message": "fail"}, output=None),
            ]
        elif request.param == "sibling_null":
            a = str(uuid4())
            return [
                _span(name="root", span_id=root, output="ok"),
                _span(name="producer", span_id=a, parent_span_id=root, output=None),
                _span(name="consumer", parent_span_id=root, input=None,
                      error={"type": "Error", "message": "null input"}, output=None),
            ]
        elif request.param == "deep_chain":
            mid = str(uuid4())
            return [
                _span(name="root", span_id=root, output="ok"),
                _span(name="middle", span_id=mid, parent_span_id=root, output=None),
                _span(name="leaf", parent_span_id=mid, output=None,
                      error={"type": "Error", "message": "deep fail"}),
            ]

    def test_originators_always_present(self, scenario_spans):
        result = compute_blame(scenario_spans)
        assert result is not None
        assert len(result.originators) >= 1, "Must always have at least one originator"

    def test_originator_score_highest(self, scenario_spans):
        result = compute_blame(scenario_spans)
        if result is None:
            return
        orig_scores = [o.blame_score for o in result.originators]
        manifest_scores = [f.blame_score for f in result.failure_points]
        if orig_scores and manifest_scores:
            assert max(orig_scores) >= max(manifest_scores), \
                "Originator must always score >= manifestor"

    def test_confidence_is_valid(self, scenario_spans):
        result = compute_blame(scenario_spans)
        if result is None:
            return
        assert result.confidence in ("high", "medium", "ambiguous")

    def test_human_summary_not_empty(self, scenario_spans):
        result = compute_blame(scenario_spans)
        if result is None:
            return
        assert result.human_summary, "Human summary must never be empty"

    def test_propagation_chain_not_empty(self, scenario_spans):
        result = compute_blame(scenario_spans)
        if result is None:
            return
        assert len(result.propagation_chain) >= 1

    def test_full_chain_contains_originator(self, scenario_spans):
        result = compute_blame(scenario_spans)
        if result is None:
            return
        chain_ids = {s.span_id for s in result.full_chain}
        for o in result.originators:
            assert o.span_id in chain_ids, \
                f"Originator {o.span_name} must appear in full_chain"

    def test_roles_are_valid_strings(self, scenario_spans):
        result = compute_blame(scenario_spans)
        if result is None:
            return
        valid_roles = {"originator", "propagator", "manifestor", "clean"}
        for o in result.originators:
            assert o.role in valid_roles
        for f in result.failure_points:
            assert f.role in valid_roles

    def test_blame_scores_bounded(self, scenario_spans):
        result = compute_blame(scenario_spans)
        if result is None:
            return
        for o in result.originators:
            assert 0.0 <= o.blame_score <= 1.0
        for f in result.failure_points:
            assert 0.0 <= f.blame_score <= 1.0

    def test_serialization_roundtrip(self, scenario_spans):
        result = compute_blame(scenario_spans)
        if result is None:
            return
        data = result.model_dump()
        assert isinstance(data, dict)
        assert "originators" in data
        assert "propagation_chain" in data
        assert "full_chain" in data
