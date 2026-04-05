"""
Blame Engine — role-based, tree-aware root-cause analysis.

Algorithm (5 passes)
--------------------
1. **Build tree** from ``parent_span_id`` relationships.
2. **Mark intrinsic state** per node: ``self_error``, ``self_null_output``,
   ``self_empty_output`` → ``self_bad``.
3. **Aggregate bottom-up**: ``subtree_bad``, ``bad_descendant_count``.
4. **Propagation top-down**: ``upstream_bad``, ``badness_inherited``.
5. **Role classification**: ORIGINATOR / PROPAGATOR / MANIFESTOR / CLEAN.

Scoring formula::

    blame_score =
        0.20 × input_anomaly
      + 0.25 × output_deviation
      + 0.10 × low_confidence
      + 0.35 × role_score
      + 0.10 × causal_proximity
"""

from __future__ import annotations

import enum
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models import BlameResponse, BlameSpan, SpanOut

logger = logging.getLogger("verdictlens.blame_engine")

# ── Weights ──────────────────────────────────────────────────────
# Weights sum to 1.0. Latency + token anomaly signals added from
# MULAN multi-modal RCA research (WWW 2024).

WEIGHT_INPUT_ANOMALY = 0.15       # reduced from 0.20
WEIGHT_OUTPUT_DEVIATION = 0.20    # reduced from 0.25
WEIGHT_LOW_CONFIDENCE = 0.08      # reduced from 0.10
WEIGHT_ROLE = 0.35                # unchanged — primary signal
WEIGHT_CAUSAL_PROXIMITY = 0.07    # reduced from 0.10
WEIGHT_LATENCY_ANOMALY = 0.08     # NEW: latency spike detection (MULAN)
WEIGHT_TOKEN_ANOMALY = 0.07       # NEW: token runaway detection (MULAN)

DEFAULT_CONFIDENCE = 0.5

CONFIDENCE_HIGH_DELTA = 0.25
CONFIDENCE_MEDIUM_DELTA = 0.10

RETRY_STORM_MIN_COUNT = 3


# ── Role enum ────────────────────────────────────────────────────

class Role(enum.Enum):
    ORIGINATOR = "originator"
    PROPAGATOR = "propagator"
    MANIFESTOR = "manifestor"
    CLEAN = "clean"


ROLE_SCORES: Dict[Role, float] = {
    Role.ORIGINATOR: 1.0,
    Role.PROPAGATOR: 0.7,
    Role.MANIFESTOR: 0.2,
    Role.CLEAN: 0.0,
}


# ── MAST failure mode detection ──────────────────────────────────
# Based on NeurIPS 2025 "Why Do Multi-Agent LLM Systems Fail?" taxonomy.
# 14 failure modes across 3 categories mapped to detectable span signals.

_CONTEXT_OVERFLOW_PATTERNS = (
    "context length", "token limit", "max tokens", "context window",
    "maximum context", "context_length_exceeded", "too long",
)
_MISSING_TOOL_PATTERNS = (
    "no such tool", "tool not found", "function not found",
    "unknown function", "undefined tool", "tool_not_found",
)
_FORMAT_ERROR_PATTERNS = (
    "jsondecodeerror", "invalid json", "parse error", "unmarshal",
    "deserializ", "json decode", "json parse", "syntaxerror",
)
_RATE_LIMIT_PATTERNS = (
    "rate limit", "ratelimit", "too many requests", "429", "quota exceeded",
)


def _detect_failure_mode(node: "SpanNode") -> Optional[str]:
    """
    Detect MAST failure mode from span signals.

    Returns a string in the form ``"category/mode"`` or None if no
    specific failure mode is identifiable.
    """
    span = node.span
    error_str = ""
    if isinstance(span.error, dict):
        error_str = (
            (span.error.get("message") or "") + " " +
            (span.error.get("type") or "")
        ).lower()
    elif isinstance(span.error, str):
        error_str = span.error.lower()

    if any(p in error_str for p in _CONTEXT_OVERFLOW_PATTERNS):
        return "system_design/context_overflow"
    if any(p in error_str for p in _MISSING_TOOL_PATTERNS):
        return "system_design/missing_tool"
    if any(p in error_str for p in _RATE_LIMIT_PATTERNS):
        return "system_design/rate_limit"
    if span.span_type == "tool" and node.self_error:
        return "system_design/tool_failure"
    if any(p in error_str for p in _FORMAT_ERROR_PATTERNS):
        return "inter_agent/wrong_output_format"
    if node.self_null_output and span.span_type in ("llm", "agent"):
        return "inter_agent/premature_termination"
    if node.self_bad_input and node.self_bad and not node.self_error:
        return "inter_agent/bad_input_propagation"

    return None


# ── Trace-level statistics (for anomaly scoring) ─────────────────

class TraceStats:
    """
    Per-trace aggregate statistics used for latency and token anomaly scoring.
    Computed once per ``compute_blame`` call and passed through to ``_score_node``.
    """

    __slots__ = ("avg_latency_ms", "avg_tokens")

    def __init__(self, spans: List[SpanOut]) -> None:
        latencies = [s.latency_ms for s in spans if s.latency_ms is not None and s.latency_ms > 0]
        tokens = [
            s.token_usage.total_tokens
            for s in spans
            if s.token_usage and s.token_usage.total_tokens
        ]
        self.avg_latency_ms: float = sum(latencies) / len(latencies) if latencies else 0.0
        self.avg_tokens: float = sum(tokens) / len(tokens) if tokens else 0.0


# ── SpanNode ─────────────────────────────────────────────────────

class SpanNode:
    """In-memory tree node wrapping a SpanOut with analysis fields."""

    __slots__ = (
        "span", "children", "parent", "depth",
        "self_error", "self_null_output", "self_empty_output", "self_bad",
        "self_bad_input",
        "subtree_bad", "bad_descendant_count",
        "upstream_bad", "badness_inherited",
        "role",
    )

    def __init__(self, span: SpanOut) -> None:
        self.span = span
        self.children: List[SpanNode] = []
        self.parent: Optional[SpanNode] = None
        self.depth: int = 0
        # Pass 2
        self.self_error: bool = False
        self.self_null_output: bool = False
        self.self_empty_output: bool = False
        self.self_bad: bool = False
        self.self_bad_input: bool = False
        # Pass 3
        self.subtree_bad: bool = False
        self.bad_descendant_count: int = 0
        # Pass 4
        self.upstream_bad: bool = False
        self.badness_inherited: bool = False
        # Pass 5
        self.role: Role = Role.CLEAN


# ── Pass 1: Build tree ──────────────────────────────────────────

def _build_tree(spans: List[SpanOut]) -> Tuple[Dict[str, SpanNode], List[SpanNode]]:
    node_map: Dict[str, SpanNode] = {}
    for s in spans:
        node_map[s.span_id] = SpanNode(s)

    roots: List[SpanNode] = []
    for s in spans:
        node = node_map[s.span_id]
        pid = s.parent_span_id
        if pid and pid in node_map:
            parent_node = node_map[pid]
            parent_node.children.append(node)
            node.parent = parent_node
        else:
            roots.append(node)

    for root in roots:
        stack = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            node.depth = depth
            for child in node.children:
                stack.append((child, depth + 1))

    return node_map, roots


# ── Pass 2: Mark intrinsic state ────────────────────────────────

def _has_error(span: SpanOut) -> bool:
    if span.error is None:
        return False
    if isinstance(span.error, dict):
        return bool(span.error.get("message") or span.error.get("type"))
    return bool(span.error)


def _is_null_output(span: SpanOut) -> bool:
    return span.output is None


def _is_empty_output(span: SpanOut) -> bool:
    out = span.output
    if out is None:
        return False
    if isinstance(out, dict) and not out:
        return True
    if isinstance(out, str) and out.strip() in ("", "null", "None", "{}"):
        return True
    if isinstance(out, list) and not out:
        return True
    return False


def _has_bad_input(span: SpanOut) -> bool:
    inp = span.input
    # None means the SDK did not record input (e.g. span takes no arguments).
    # Treat as neutral rather than bad to avoid false-positive blame attribution.
    if inp is None:
        return False
    if isinstance(inp, dict) and not inp:
        return True
    if isinstance(inp, str) and inp.strip() in ("", "null", "None"):
        return True
    # SDK wraps inputs as {"args": [...], "kwargs": {...}}.
    # A null positional arg means the caller passed None.
    if isinstance(inp, dict):
        args = inp.get("args")
        if isinstance(args, list) and args and any(a is None for a in args):
            return True
    return False


def _mark_intrinsic(node_map: Dict[str, SpanNode]) -> None:
    for node in node_map.values():
        node.self_error = _has_error(node.span)
        node.self_null_output = _is_null_output(node.span)
        node.self_empty_output = _is_empty_output(node.span)
        node.self_bad = node.self_error or node.self_null_output or node.self_empty_output
        node.self_bad_input = _has_bad_input(node.span)


# ── Pass 3: Aggregate bottom-up ─────────────────────────────────

def _aggregate_bottom_up(root: SpanNode) -> None:
    """
    Iterative post-order bottom-up aggregation.

    Avoids Python recursion limits for deep span trees (>1000 levels).
    """
    # Collect nodes in reverse-pre-order → equivalent to post-order when reversed.
    post_order: List[SpanNode] = []
    stack: List[SpanNode] = [root]
    while stack:
        node = stack.pop()
        post_order.append(node)
        stack.extend(node.children)

    # Process children before parents.
    for node in reversed(post_order):
        child_bad_sum = sum(
            child.bad_descendant_count + (1 if child.self_bad else 0)
            for child in node.children
        )
        node.bad_descendant_count = child_bad_sum
        node.subtree_bad = node.self_bad or node.bad_descendant_count > 0


# ── Pass 4: Propagation top-down ────────────────────────────────

def _propagation_top_down(root: SpanNode, ancestor_is_bad: bool = False) -> None:
    """
    Iterative pre-order top-down propagation.

    Avoids Python recursion limits for deep span trees (>1000 levels).
    """
    stack: List[Tuple[SpanNode, bool]] = [(root, ancestor_is_bad)]
    while stack:
        node, anc_bad = stack.pop()
        node.upstream_bad = anc_bad
        node.badness_inherited = node.self_bad and anc_bad

        # If this node is bad AND has bad descendants, its own badness is
        # likely *explained* by those descendants (exception bubbled up, or
        # null output because a child produced null).  Don't mark children
        # as upstream_bad — that would invert causality and make the true
        # originator child look like a manifestor.
        if node.self_bad and node.bad_descendant_count > 0:
            propagate = anc_bad
        else:
            propagate = anc_bad or node.self_bad

        for child in node.children:
            stack.append((child, propagate))


# ── Pass 4b: Sibling propagation ────────────────────────────────

def _sibling_propagation(node_map: Dict[str, SpanNode]) -> None:
    """
    Detect sibling-to-sibling data flow: if a span has bad input and a
    sibling (same parent) has bad output WITHOUT bad input, the span's
    badness is inherited from the sibling.

    The "without bad input" condition prevents two mutual victims from
    marking each other as inherited — only a sibling that genuinely
    *introduced* bad output (not itself receiving garbage) can be a source.
    """
    for node in node_map.values():
        if not node.self_bad or not node.self_bad_input or node.badness_inherited:
            continue
        if node.parent is None:
            continue
        for sibling in node.parent.children:
            if sibling is node:
                continue
            sibling_has_bad_output = (
                sibling.self_null_output or sibling.self_empty_output
            )
            sibling_introduced_it = sibling_has_bad_output and not sibling.self_bad_input
            if sibling_introduced_it:
                node.upstream_bad = True
                node.badness_inherited = True
                break


# ── Pass 4c: Data-flow propagation ──────────────────────────────

def _data_flow_propagation(node_map: Dict[str, SpanNode]) -> None:
    """
    Pass 4c — use SDK-recorded ``source_span_ids`` to detect cross-subtree
    data dependencies that parent-chain traversal cannot see.

    When a span carries the output of a bad upstream span as its input
    (proven by object identity at call time, not string matching), that
    downstream span's badness is inherited — not self-originated.

    This is the critical correction for orchestrator / fan-in topologies
    where sibling spans pass results to one another.
    """
    for node in node_map.values():
        source_ids = node.span.source_span_ids or []
        if not source_ids:
            continue
        for src_id in source_ids:
            src = node_map.get(src_id)
            if src is not None and src.self_bad:
                # The input this node received came from a bad upstream span.
                node.upstream_bad = True
                if node.self_bad:
                    node.badness_inherited = True
                break


# ── Pass 5: Role classification ─────────────────────────────────

def _classify_roles(node_map: Dict[str, SpanNode]) -> None:
    """
    Assign roles using the pre-computed ``upstream_bad`` and ``badness_inherited``
    fields from Pass 4 + 4b.  This correctly handles both parent-child and
    sibling propagation.
    """
    for node in node_map.values():
        if not node.subtree_bad and not node.self_bad:
            node.role = Role.CLEAN
        elif node.self_bad and not node.upstream_bad:
            # A node whose badness is explained by its descendants
            # (error bubbled up, or null output caused by child null)
            # is a propagator, not the originator.
            if node.bad_descendant_count > 0:
                node.role = Role.PROPAGATOR
            else:
                node.role = Role.ORIGINATOR
        elif node.self_bad and node.upstream_bad and node.bad_descendant_count > 0:
            node.role = Role.PROPAGATOR
        elif node.self_bad and node.upstream_bad:
            node.role = Role.MANIFESTOR
        elif not node.self_bad and node.subtree_bad:
            node.role = Role.CLEAN
        else:
            node.role = Role.CLEAN


# ── Scoring ──────────────────────────────────────────────────────

def _input_anomaly_score(span: SpanOut) -> float:
    inp = span.input
    if inp is None:
        return 1.0
    if isinstance(inp, dict):
        if not inp:
            return 1.0
        null_count = sum(1 for v in inp.values() if v is None or v == "" or v == "null")
        ratio = null_count / len(inp) if inp else 0
        if ratio > 0.5:
            return 0.8
        if ratio > 0:
            return 0.5
    if isinstance(inp, str) and inp.strip() in ("", "null", "None"):
        return 1.0
    return 0.0


def _output_deviation_score(span: SpanOut) -> float:
    if _has_error(span):
        return 1.0
    out = span.output
    if out is None:
        return 1.0
    if isinstance(out, dict):
        if not out:
            return 0.8
        null_count = sum(1 for v in out.values() if v is None or v == "" or v == "null")
        ratio = null_count / len(out) if out else 0
        if ratio > 0.5:
            return 0.7
        if ratio > 0:
            return 0.3
    if isinstance(out, str) and out.strip() in ("", "null", "None"):
        return 1.0
    return 0.0


def _low_confidence_penalty(span: SpanOut) -> float:
    cs = span.confidence_score
    if cs is None:
        return 1.0 - DEFAULT_CONFIDENCE
    return 1.0 - max(0.0, min(1.0, cs))


def _causal_proximity(node: SpanNode, max_depth: int) -> float:
    if max_depth == 0:
        return 0.5
    return node.depth / max_depth


def _latency_anomaly_score(span: SpanOut, stats: TraceStats) -> float:
    """
    Detect latency spikes relative to trace average (MULAN multi-modal signal).
    A span with 5× average latency is a strong anomaly indicator.
    """
    if span.latency_ms is None or stats.avg_latency_ms == 0:
        return 0.0
    ratio = span.latency_ms / stats.avg_latency_ms
    if ratio >= 5.0:
        return 1.0
    if ratio >= 3.0:
        return 0.7
    if ratio >= 2.0:
        return 0.4
    return 0.0


def _token_anomaly_score(span: SpanOut, stats: TraceStats) -> float:
    """
    Detect token runaway relative to trace average (MULAN multi-modal signal).
    A span consuming 10× average tokens indicates a prompt loop or explosion.
    """
    if not span.token_usage or not span.token_usage.total_tokens or stats.avg_tokens == 0:
        return 0.0
    ratio = span.token_usage.total_tokens / stats.avg_tokens
    if ratio >= 10.0:
        return 1.0
    if ratio >= 5.0:
        return 0.6
    if ratio >= 3.0:
        return 0.3
    return 0.0


def _score_node(node: SpanNode, max_depth: int, stats: Optional[TraceStats] = None) -> float:
    span = node.span
    total = (
        WEIGHT_INPUT_ANOMALY * _input_anomaly_score(span)
        + WEIGHT_OUTPUT_DEVIATION * _output_deviation_score(span)
        + WEIGHT_LOW_CONFIDENCE * _low_confidence_penalty(span)
        + WEIGHT_ROLE * ROLE_SCORES[node.role]
        + WEIGHT_CAUSAL_PROXIMITY * _causal_proximity(node, max_depth)
    )
    if stats is not None:
        total += WEIGHT_LATENCY_ANOMALY * _latency_anomaly_score(span, stats)
        total += WEIGHT_TOKEN_ANOMALY * _token_anomaly_score(span, stats)
    return max(0.0, min(1.0, total))


# ── Retry storm detection ────────────────────────────────────────

def _detect_retry_storm(
    node_map: Dict[str, SpanNode],
) -> Tuple[bool, Set[str]]:
    """
    Detect retry storms: 3+ spans with the same (name, parent_span_id) that
    all have errors, within a tight time window.

    Returns (is_storm, set of span_ids to suppress — all except the first).
    """
    from collections import defaultdict

    groups: Dict[Tuple[str, Optional[str]], List[SpanNode]] = defaultdict(list)
    for node in node_map.values():
        key = (node.span.name, node.span.parent_span_id)
        groups[key].append(node)

    storm_detected = False
    suppress_ids: Set[str] = set()

    for _key, nodes in groups.items():
        error_nodes = [n for n in nodes if n.self_error]
        if len(error_nodes) < RETRY_STORM_MIN_COUNT:
            continue

        error_nodes.sort(key=lambda n: n.span.start_time or "")

        latencies = [n.span.latency_ms for n in error_nodes if n.span.latency_ms]
        if latencies:
            median_lat = sorted(latencies)[len(latencies) // 2]
        else:
            median_lat = 1000.0

        first_start = error_nodes[0].span.start_time or ""
        last_start = error_nodes[-1].span.start_time or ""
        if first_start and last_start:
            total_window_ms = sum(
                n.span.latency_ms or median_lat for n in error_nodes
            )
            threshold_ms = 2.0 * median_lat * len(error_nodes)
            if total_window_ms <= threshold_ms:
                storm_detected = True
                for n in error_nodes[1:]:
                    suppress_ids.add(n.span.span_id)

    return storm_detected, suppress_ids


# ── Reason & summary builders ────────────────────────────────────

def _error_message(span: SpanOut) -> str:
    if isinstance(span.error, dict):
        etype = span.error.get("type", "Error")
        emsg = span.error.get("message", "unknown error")
        return f"{etype}: {emsg}"
    if isinstance(span.error, str):
        return span.error
    return "unknown error"


def _build_reason(node: SpanNode) -> str:
    span = node.span
    parts: List[str] = []

    if node.self_error:
        parts.append(f"error: {_error_message(span)}")
    if node.self_null_output:
        parts.append("produced null output")
    elif node.self_empty_output:
        parts.append("produced empty output")
    if node.badness_inherited:
        parts.append("received bad state from upstream")

    if node.role == Role.ORIGINATOR:
        if node.bad_descendant_count > 0:
            parts.append(f"caused {node.bad_descendant_count} downstream failure(s)")
    elif node.role == Role.PROPAGATOR:
        parts.append("propagated failure downstream")
    elif node.role == Role.MANIFESTOR:
        parts.append("failure manifested here due to upstream issue")

    cs = span.confidence_score
    if cs is not None and cs < 0.4:
        parts.append(f"low confidence ({cs:.2f})")

    if node.depth > 0:
        parts.append(f"depth {node.depth} in span tree")

    if not parts:
        parts.append("highest composite anomaly score")

    return f"{span.name}: " + "; ".join(parts)


def _find_secondary_contributors(
    originator: SpanNode,
    node_map: Dict[str, SpanNode],
) -> List[SpanNode]:
    """Find child spans of the originator that have errors (deeper root causes)."""
    secondaries: List[SpanNode] = []
    for child in originator.children:
        if child.self_error:
            secondaries.append(child)
    return secondaries


def _build_propagation_chain(
    node_map: Dict[str, SpanNode],
    roots: List[SpanNode],
) -> List[str]:
    """
    Iterative DFS, emitting narrative strings for spans on failure paths.

    Avoids Python recursion limits for deep span trees (>1000 levels).
    """
    chain: List[str] = []
    # Push roots in reverse so first root is processed first.
    stack: List[SpanNode] = list(reversed(roots))
    while stack:
        node = stack.pop()
        if not node.subtree_bad and not node.self_bad:
            continue
        span = node.span
        if node.role == Role.ORIGINATOR:
            if node.self_error:
                chain.append(f"{span.name} failed: {_error_message(span)}")
            else:
                chain.append(f"{span.name} produced bad output (root cause)")
        elif node.role == Role.PROPAGATOR:
            chain.append(f"{span.name} propagated failure downstream")
        elif node.role == Role.MANIFESTOR:
            if node.self_error:
                chain.append(f"{span.name} failed: {_error_message(span)} (caused by upstream)")
            else:
                chain.append(f"{span.name} received bad input (failure point)")
        elif node.self_bad:
            chain.append(f"{span.name}: downstream failure — {node.bad_descendant_count} error(s) in subtree")
        # Push children in reverse to maintain left-to-right DFS order.
        stack.extend(reversed(node.children))

    return chain if chain else ["No detailed chain available"]


def _build_full_chain(
    originators: List[SpanNode],
    node_map: Dict[str, SpanNode],
) -> List[SpanOut]:
    """
    Collect all spans on failure paths from originators through to manifestors.

    Uses iterative post-order traversal to avoid Python recursion limits.
    """
    chain_ids: Set[str] = set()

    for root in (n for n in node_map.values() if n.parent is None):
        # Collect in reverse-pre-order; reversed() gives post-order.
        rpo: List[SpanNode] = []
        stack: List[SpanNode] = [root]
        while stack:
            node = stack.pop()
            rpo.append(node)
            stack.extend(node.children)

        on_path_map: Dict[str, bool] = {}
        for node in reversed(rpo):
            child_on_path = any(on_path_map.get(c.span.span_id, False) for c in node.children)
            if node.role == Role.CLEAN:
                on_path = child_on_path
            else:
                on_path = node.role in (Role.ORIGINATOR, Role.PROPAGATOR, Role.MANIFESTOR) or child_on_path
            on_path_map[node.span.span_id] = on_path
            if on_path:
                chain_ids.add(node.span.span_id)

    if not chain_ids and originators:
        chain_ids.add(originators[0].span.span_id)

    # Pre-order DFS to collect spans in tree order.
    ordered: List[SpanOut] = []
    for root in (n for n in node_map.values() if n.parent is None):
        stack = [root]
        while stack:
            node = stack.pop()
            if node.span.span_id in chain_ids:
                ordered.append(node.span)
            stack.extend(reversed(node.children))

    return ordered if ordered else [originators[0].span] if originators else []


def _build_human_summary(
    originators: List[SpanNode],
    manifestors: List[SpanNode],
    secondaries: List[SpanNode],
    confidence: str,
) -> str:
    if not originators:
        return "No clear root cause identified."

    if len(originators) > 1 and confidence == "ambiguous":
        names = ", ".join(n.span.name for n in originators)
        return (
            f"Multiple independent failures detected ({names}). "
            f"No single root cause — these appear to be co-originators."
        )

    orig = originators[0]
    parts: List[str] = []

    if orig.self_error:
        parts.append(f"{orig.span.name} failed with {_error_message(orig.span)}")
    elif orig.self_null_output or orig.self_empty_output:
        parts.append(f"{orig.span.name} produced {'null' if orig.self_null_output else 'empty'} output")

    if secondaries:
        sec = secondaries[0]
        parts.append(f"(triggered by {_error_message(sec.span)} in {sec.span.name})")

    if manifestors:
        names = ", ".join(m.span.name for m in manifestors[:3])
        verb = "propagated to" if len(manifestors) == 1 else "caused failures in"
        parts.append(f"This {verb} {names}.")

    if not parts:
        parts.append(f"{orig.span.name} was identified as the root cause.")

    return " ".join(parts)


# ── LLM explanation layer (COCA + RCACopilot) ────────────────────

def generate_llm_summary(blame: BlameResponse, model: str = "gpt-4o-mini") -> str:
    """
    Generate a richer root cause explanation using Chain-of-Thought prompting.

    Inspired by COCA (arXiv 2503.23051) and RCACopilot (EuroSys 2024).
    Falls back to the existing ``human_summary`` if no LLM key is available
    or if the call fails.

    :param blame: Completed blame analysis result.
    :param model: LLM model to use for explanation generation.
    :returns: Human-readable explanation string.
    """
    try:
        from app.replay import _execute_llm_call

        originators = [
            f"{s.span_name} (score={s.blame_score:.2f}"
            + (f", mode={s.failure_mode}" if s.failure_mode else "") + ")"
            for s in blame.originators
        ]
        failure_points = [s.span_name for s in blame.failure_points]
        chain = blame.propagation_chain[:8]  # cap to avoid token overflow

        prompt = (
            "You are an AI agent debugging assistant. Analyze this failure report "
            "and explain the root cause in 2-3 sentences a developer can act on.\n\n"
            f"Confidence: {blame.confidence}\n"
            f"Root cause agent(s): {', '.join(originators) if originators else 'unknown'}\n"
            f"Where failure surfaced: {', '.join(failure_points) if failure_points else 'unknown'}\n"
            f"Propagation chain:\n" + "\n".join(f"  - {step}" for step in chain) + "\n\n"
            "Think step by step:\n"
            "1. What specifically went wrong?\n"
            "2. Why did it propagate?\n"
            "3. What should the developer fix?\n\n"
            "Answer (2-3 sentences, be specific and actionable):"
        )

        result, error, _, _, _, _ = _execute_llm_call(
            model=model,
            original_input=None,
            new_input={"messages": [{"role": "user", "content": prompt}]},
        )

        if error or not result:
            return blame.human_summary

        content = result.get("content", "") if isinstance(result, dict) else str(result)
        content = content.strip()
        return content if content else blame.human_summary

    except Exception as exc:
        logger.debug("verdictlens: llm summary generation failed: %s", exc)
        return blame.human_summary


# ── Public API ───────────────────────────────────────────────────

def compute_blame(spans: List[SpanOut]) -> Optional[BlameResponse]:
    """
    Run v2 blame analysis on a list of spans from a single trace.

    Returns None if the trace has no bad spans.
    """
    if not spans:
        return None

    # Compute trace-level statistics once for anomaly scoring
    trace_stats = TraceStats(spans)

    # Pass 1: Build tree
    node_map, roots = _build_tree(spans)

    # Pass 2: Mark intrinsic state
    _mark_intrinsic(node_map)

    bad_nodes = [n for n in node_map.values() if n.self_bad]
    if not bad_nodes:
        return None

    # Pass 3: Aggregate bottom-up
    for root in roots:
        _aggregate_bottom_up(root)

    # Pass 4: Propagation top-down
    for root in roots:
        _propagation_top_down(root, ancestor_is_bad=False)

    # Pass 4b: Sibling propagation (orchestrator pattern)
    _sibling_propagation(node_map)

    # Pass 4c: Data-flow propagation via SDK-tracked object identity lineage
    _data_flow_propagation(node_map)

    # Pass 5: Role classification
    _classify_roles(node_map)

    # Retry storm detection
    retry_storm, suppress_ids = _detect_retry_storm(node_map)

    # Score all nodes (suppress retry duplicates)
    max_depth = max(n.depth for n in node_map.values()) if node_map else 0
    scored: Dict[str, float] = {}
    for node in node_map.values():
        if node.span.span_id in suppress_ids:
            scored[node.span.span_id] = 0.0
        else:
            scored[node.span.span_id] = _score_node(node, max_depth, trace_stats)

    # Rank
    ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)

    # Confidence — compare only among ORIGINATOR-role spans.
    # A MANIFESTOR scoring close to an ORIGINATOR is expected (victim of the
    # same failure) and should not lower confidence.
    originator_scores = sorted(
        [scored[sid] for sid, n in node_map.items() if n.role == Role.ORIGINATOR],
        reverse=True,
    )
    if len(originator_scores) >= 2:
        delta = originator_scores[0] - originator_scores[1]
    elif originator_scores:
        delta = 1.0
    else:
        delta = ranked[0][1] - (ranked[1][1] if len(ranked) > 1 else 0.0) if ranked else 0.0

    if delta > CONFIDENCE_HIGH_DELTA:
        confidence = "high"
    elif delta > CONFIDENCE_MEDIUM_DELTA:
        confidence = "medium"
    else:
        confidence = "ambiguous"

    # Collect originators
    originator_nodes = [
        node_map[sid] for sid, _ in ranked
        if node_map[sid].role == Role.ORIGINATOR
    ]

    if not originator_nodes:
        originator_nodes = [node_map[ranked[0][0]]] if ranked else []

    if confidence == "ambiguous" and len(ranked) >= 2:
        second_node = node_map[ranked[1][0]]
        if (
            second_node not in originator_nodes
            and second_node.role not in (Role.CLEAN, Role.MANIFESTOR)
        ):
            originator_nodes.append(second_node)

    # Collect manifestors
    manifestor_nodes = [
        n for n in node_map.values() if n.role == Role.MANIFESTOR
    ]

    # Secondary contributors
    all_secondaries: List[SpanNode] = []
    for orig in originator_nodes:
        all_secondaries.extend(_find_secondary_contributors(orig, node_map))

    # Build outputs
    propagation_chain = _build_propagation_chain(node_map, roots)
    full_chain = _build_full_chain(originator_nodes, node_map)

    def _make_blame_span(node: SpanNode, caused_by: Optional[str] = None) -> BlameSpan:
        return BlameSpan(
            span_id=node.span.span_id,
            span_name=node.span.name,
            role=node.role.value,
            blame_score=round(scored.get(node.span.span_id, 0.0), 4),
            reason=_build_reason(node),
            caused_by=caused_by,
            failure_mode=_detect_failure_mode(node),
        )

    originator_spans = [_make_blame_span(n) for n in originator_nodes]

    failure_point_spans = []
    for m in manifestor_nodes:
        caused_by_name = None
        ancestor = m.parent
        while ancestor:
            if ancestor.role == Role.ORIGINATOR:
                caused_by_name = ancestor.span.name
                break
            if ancestor.role == Role.PROPAGATOR:
                caused_by_name = ancestor.span.name
                break
            ancestor = ancestor.parent
        failure_point_spans.append(_make_blame_span(m, caused_by=caused_by_name))

    secondary_spans = [_make_blame_span(n) for n in all_secondaries]

    human_summary = _build_human_summary(
        originator_nodes, manifestor_nodes, all_secondaries, confidence,
    )

    return BlameResponse(
        originators=originator_spans,
        failure_points=failure_point_spans,
        secondary_contributors=secondary_spans,
        propagation_chain=propagation_chain,
        confidence=confidence,
        human_summary=human_summary,
        retry_storm=retry_storm,
        full_chain=full_chain,
    )
