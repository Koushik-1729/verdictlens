"""
Replay / Time-Travel Debugging engine.

Given a span_id and new input, re-executes the LLM call with modified input
and returns a side-by-side diff with real output, real latency, real cost,
and real token counts.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field

from app.clickhouse import _get_client, _safe_json, _parse_json_field, _fmt_dt
from app.settings import get_settings

logger = logging.getLogger("verdictlens.replay")

# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------

_GROQ_KEYWORDS = ("llama", "mixtral", "gemma2-", "whisper")
_XAI_KEYWORDS = ("grok",)
_OPENAI_KEYWORDS = ("gpt", "o1-", "o3-", "o4-", "text-embedding", "davinci", "babbage")
_NVIDIA_KEYWORDS = ("nvidia/", "google/gemma", "meta/llama", "mistralai/", "microsoft/", "qwen")
_ANTHROPIC_KEYWORDS = ("claude",)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_XAI_BASE_URL = "https://api.x.ai/v1"
_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
_ANTHROPIC_OPENAI_BASE_URL = "https://api.anthropic.com/v1"

_COST_PER_MILLION: Dict[str, Tuple[float, float]] = {
    "gpt-4o": (5.0, 15.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-3.5-turbo": (0.50, 1.50),
    "llama-3.3-70b": (0.59, 0.79),
    "llama-3.1-70b": (0.59, 0.79),
    "llama-3.1-8b": (0.05, 0.08),
    "mixtral-8x7b": (0.24, 0.24),
    "gemma2-9b": (0.20, 0.20),
    "grok-4": (3.0, 15.0),
    "grok-3": (3.0, 15.0),
    "grok-3-mini": (0.30, 0.50),
}

# ---------------------------------------------------------------------------
# Public schemas
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    """Request body for POST /traces/{id}/spans/{span_id}/replay."""

    new_input: Dict[str, Any]
    note: Optional[str] = None


class ReplayResult(BaseModel):
    """Side-by-side comparison of original vs replayed span."""

    original_span_id: str
    replay_span_id: str
    original_input: Optional[Dict[str, Any]] = None
    new_input: Dict[str, Any]
    original_output: Optional[Any] = None
    new_output: Optional[Any] = None
    original_latency_ms: float = 0.0
    new_latency_ms: float = 0.0
    original_cost_usd: float = 0.0
    new_cost_usd: float = 0.0
    original_tokens: int = 0
    new_tokens: int = 0
    output_diff: List[str] = Field(default_factory=list)
    status: Literal["same", "improved", "degraded", "different"] = "different"
    improvement_score: Optional[float] = None
    suspiciousness_score: Optional[float] = None  # SBFL-inspired (arXiv 2405.00565)
    note: Optional[str] = None
    parent_context: Optional[Dict[str, Any]] = None
    tree_position: Optional[Dict[str, Any]] = None


class ReplaySummary(BaseModel):
    """Summary of a single replay attempt, returned in list endpoints."""

    replay_span_id: str
    original_span_id: str
    original_span_name: str
    note: Optional[str] = None
    status: Literal["same", "improved", "degraded", "different"] = "different"
    created_at: str


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def execute_replay(
    trace_id: str,
    span_id: str,
    request: ReplayRequest,
    *,
    workspace_id: str = "default",
) -> ReplayResult:
    """
    Replay a span by re-executing the LLM call with new input.

    For child spans, reconstructs the parent chain context so the
    replayed call has the same environmental data as the original.

    :param trace_id: Parent trace id.
    :param span_id: Original span id to replay.
    :param request: Replay request with new_input and optional note.
    :param workspace_id: Workspace scope for trace/span lookups.
    :returns: :class:`ReplayResult` with side-by-side comparison.
    :raises ValueError: If span not found, is a replay, or has no model.
    """
    if not workspace_id:
        raise ValueError("workspace_id is required")

    settings = get_settings()
    ch = _get_client(settings)
    db = settings.ch_database

    original = _fetch_span_full(ch, db, trace_id, span_id, workspace_id=workspace_id)
    if original is None:
        raise ValueError(f"Span {span_id} not found in trace {trace_id}")

    if original.get("is_replay"):
        raise ValueError(f"Span {span_id} is already a replay — no replay of replays")

    original_input = _parse_json_field(original["input"])
    original_output = _parse_json_field(original["output"])
    original_error = _parse_json_field(original["error"])
    original_latency = float(original["latency_ms"] or 0)
    original_cost = float(original["cost_usd"] or 0)
    original_tokens = int(original["total_tokens"] or 0)
    model = original["model"]
    parent_span_id = original.get("parent_span_id")

    # Fetch all spans once; reuse for parent-chain traversal and tree-position
    # to avoid N+1 ClickHouse queries (one per ancestor depth level).
    span_lookup = _fetch_trace_span_lookup(ch, db, trace_id)
    parent_context = _reconstruct_parent_context(ch, db, trace_id, parent_span_id, span_lookup=span_lookup)
    tree_position = _compute_tree_position(ch, db, trace_id, span_id, parent_span_id, span_lookup=span_lookup)

    new_output, new_error, new_latency, new_cost, new_tokens, token_detail = (
        _execute_llm_call(
            model=model,
            original_input=original_input,
            new_input=request.new_input,
            parent_context=parent_context,
        )
    )

    status = _compute_status(original_output, new_output, original_error, new_error)
    improvement = _compute_improvement(
        status, original_latency, new_latency, original_cost, new_cost,
    )
    suspiciousness = _compute_suspiciousness(
        original_output, new_output, original_error, new_error, status,
    )
    output_diff = _compute_diff(original_output, new_output)

    replay_span_id = str(uuid4())
    now = datetime.now(timezone.utc)

    _store_replay_span(
        client=ch,
        db=db,
        replay_span_id=replay_span_id,
        original_span_id=span_id,
        trace_id=trace_id,
        name=original["name"],
        span_type=original["span_type"],
        model=model,
        parent_span_id=parent_span_id,
        new_input=request.new_input,
        new_output=new_output,
        new_error=new_error,
        latency_ms=new_latency,
        cost_usd=new_cost,
        total_tokens=new_tokens,
        prompt_tokens=token_detail.get("prompt_tokens"),
        completion_tokens=token_detail.get("completion_tokens"),
        note=request.note,
        status=status,
        now=now,
        workspace_id=workspace_id,
    )

    return ReplayResult(
        original_span_id=span_id,
        replay_span_id=replay_span_id,
        original_input=(
            original_input if isinstance(original_input, dict) else {"raw": original_input}
        ),
        new_input=request.new_input,
        original_output=original_output,
        new_output=new_output,
        original_latency_ms=original_latency,
        new_latency_ms=new_latency,
        original_cost_usd=original_cost,
        new_cost_usd=new_cost,
        original_tokens=original_tokens,
        new_tokens=new_tokens,
        output_diff=output_diff,
        status=status,
        improvement_score=improvement,
        suspiciousness_score=suspiciousness,
        note=request.note,
        parent_context=parent_context,
        tree_position=tree_position,
    )


def list_replays(trace_id: str, *, workspace_id: str = "default") -> List[ReplaySummary]:
    """
    List all replay attempts for a trace, ordered by most recent first.

    :param trace_id: Trace identifier.
    :param workspace_id: Workspace scope.
    :returns: List of :class:`ReplaySummary`.
    """
    if not workspace_id:
        raise ValueError("workspace_id is required")

    settings = get_settings()
    ch = _get_client(settings)
    db = settings.ch_database

    # Select metadata so we can read replay_status directly — no per-row queries.
    sql = (
        f"SELECT span_id, original_span_id, name, replay_note, inserted_at, metadata "
        f"FROM {db}.spans "
        f"WHERE trace_id = {{tid:String}} AND is_replay = true "
        f"AND workspace_id = {{_ws:String}} "
        f"ORDER BY inserted_at DESC"
    )
    result = ch.query(sql, parameters={"tid": trace_id, "_ws": workspace_id})

    summaries: List[ReplaySummary] = []
    for row in result.result_rows:
        meta = _parse_json_field(row[5]) or {}
        status: str = meta.get("replay_status", "different")
        summaries.append(ReplaySummary(
            replay_span_id=row[0],
            original_span_id=row[1] or "",
            original_span_name=row[2],
            note=row[3],
            status=status,  # type: ignore[arg-type]
            created_at=_fmt_dt(row[4]) or "",
        ))
    return summaries


# ---------------------------------------------------------------------------
# LLM execution
# ---------------------------------------------------------------------------


def _execute_llm_call(
    *,
    model: Optional[str],
    original_input: Any,
    new_input: Dict[str, Any],
    parent_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Any, float, float, int, Dict[str, Optional[int]]]:
    """
    Call the LLM for real and return (output, error, latency_ms, cost, total_tokens, token_detail).

    When parent_context is provided, it is injected as a system message
    prefix so the LLM has the same environmental context as the original call.

    :param model: Model name from the original span.
    :param original_input: Original span's stored input (used to reconstruct messages).
    :param new_input: User-edited input dict.
    :param parent_context: Reconstructed parent chain context for child spans.
    :returns: 6-tuple of results.
    :raises ValueError: If model is missing or no API key is configured.
    """
    import openai as openai_lib

    if not model:
        raise ValueError(
            "Cannot replay: original span has no model. "
            "Replay only works on spans that recorded a model name."
        )

    base_url, api_key, effective_model = _resolve_provider(model)
    if not api_key:
        raise ValueError(
            "Cannot replay: no LLM API key configured. "
            "Set at least one of GROQ_API_KEY, OPENAI_API_KEY, or XAI_API_KEY in your .env."
        )

    messages = _build_messages(new_input, original_input)

    if parent_context and parent_context.get("chain"):
        context_text = _format_parent_context(parent_context)
        messages = [
            {"role": "system", "content": context_text},
            *messages,
        ]

    call_model = new_input.get("model") or effective_model
    temperature = new_input.get("temperature")

    client_kwargs: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    llm = openai_lib.OpenAI(**client_kwargs)

    create_kwargs: Dict[str, Any] = {"model": call_model, "messages": messages}
    if temperature is not None:
        create_kwargs["temperature"] = temperature

    t0 = time.perf_counter()
    token_detail: Dict[str, Optional[int]] = {}
    try:
        response = llm.chat.completions.create(**create_kwargs)
        latency_ms = round((time.perf_counter() - t0) * 1000, 3)

        content = (
            response.choices[0].message.content
            if response.choices
            else None
        )
        output: Any = {"role": "assistant", "content": content}

        if response.usage:
            token_detail = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        total_tokens = token_detail.get("total_tokens") or 0
        cost = _estimate_cost(call_model, token_detail)
        return output, None, latency_ms, cost, total_tokens, token_detail

    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 3)
        error_detail = {"type": type(exc).__name__, "message": str(exc)}
        logger.warning("verdictlens: replay LLM call failed: %s", exc)
        return None, error_detail, latency_ms, 0.0, 0, token_detail


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def _resolve_provider(model: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Map a model name to (base_url, api_key, model_to_use).

    Tries the native provider first. If that provider's key is missing,
    falls back to any available provider with a compatible default model.

    Provider detection order (most-specific first):
      NVIDIA NIM  — model names with "/" or known NIM prefixes
      xAI         — grok-* models
      OpenAI      — gpt-*, o1-*, o3-*, o4-*, embeddings, completions
      Anthropic   — claude-* (via openai-compat shim — requires ANTHROPIC_API_KEY)
      Groq        — llama-*, gemma2-*, mixtral-*, whisper-*

    :returns: (base_url, api_key, effective_model). api_key is None when no key exists.
    """
    m = model.lower()

    # NVIDIA NIM: model names contain "/" (e.g. "google/gemma-2-9b-it") or NIM prefixes
    if any(kw in m for kw in _NVIDIA_KEYWORDS):
        key = os.environ.get("NVIDIA_API_KEY")
        if key:
            return _NVIDIA_BASE_URL, key, model

    # xAI Grok
    if any(kw in m for kw in _XAI_KEYWORDS):
        key = os.environ.get("XAI_API_KEY")
        if key:
            return _XAI_BASE_URL, key, model

    # OpenAI
    if any(kw in m for kw in _OPENAI_KEYWORDS):
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            return None, key, model

    # Anthropic (openai-compat endpoint)
    if any(kw in m for kw in _ANTHROPIC_KEYWORDS):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return _ANTHROPIC_OPENAI_BASE_URL, key, model

    # Groq
    if any(kw in m for kw in _GROQ_KEYWORDS):
        key = os.environ.get("GROQ_API_KEY")
        if key:
            return _GROQ_BASE_URL, key, model

    # Fallback: use whichever provider has a key, with a safe default model
    _FALLBACKS: List[Tuple[str, Optional[str], str]] = [
        ("NVIDIA_API_KEY", _NVIDIA_BASE_URL, "meta/llama-3.3-70b-instruct"),
        ("GROQ_API_KEY", _GROQ_BASE_URL, "llama-3.3-70b-versatile"),
        ("OPENAI_API_KEY", None, "gpt-4o-mini"),
        ("XAI_API_KEY", _XAI_BASE_URL, "grok-3-mini"),
    ]
    for env_key, base, default_model in _FALLBACKS:
        key = os.environ.get(env_key)
        if key:
            logger.info(
                "verdictlens: no key for model %s, falling back to %s (%s)",
                model, env_key, default_model,
            )
            return base, key, default_model

    return None, None, model


def _provider_name(model: str) -> str:
    """Human-readable provider name for error messages."""
    m = model.lower()
    if any(kw in m for kw in _NVIDIA_KEYWORDS):
        return "NVIDIA NIM"
    if any(kw in m for kw in _XAI_KEYWORDS):
        return "xAI"
    if any(kw in m for kw in _OPENAI_KEYWORDS):
        return "OpenAI"
    if any(kw in m for kw in _ANTHROPIC_KEYWORDS):
        return "Anthropic"
    return "Groq"


def _env_var_for(model: str) -> str:
    """Environment variable name needed for the model's provider."""
    m = model.lower()
    if any(kw in m for kw in _NVIDIA_KEYWORDS):
        return "NVIDIA_API_KEY"
    if any(kw in m for kw in _XAI_KEYWORDS):
        return "XAI_API_KEY"
    if any(kw in m for kw in _OPENAI_KEYWORDS):
        return "OPENAI_API_KEY"
    if any(kw in m for kw in _ANTHROPIC_KEYWORDS):
        return "ANTHROPIC_API_KEY"
    return "GROQ_API_KEY"


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


def _build_messages(
    new_input: Dict[str, Any], original_input: Any,
) -> List[Dict[str, str]]:
    """
    Build chat completion messages from user-edited input.

    Priority:
    1. new_input has "messages" key → use directly (user edited an LLM span).
    2. original_input had "messages" → use as template, replace last user content.
    3. Fallback → wrap new_input values as a single user message.

    :returns: List of message dicts ready for chat.completions.create.
    """
    if "messages" in new_input and isinstance(new_input["messages"], list):
        return new_input["messages"]

    if isinstance(original_input, dict) and "messages" in original_input:
        orig_msgs = original_input["messages"]
        if isinstance(orig_msgs, list) and orig_msgs:
            msgs = [dict(m) if isinstance(m, dict) else m for m in orig_msgs]
            # Replace the last user message with new_input content
            for i in range(len(msgs) - 1, -1, -1):
                if isinstance(msgs[i], dict) and msgs[i].get("role") == "user":
                    msgs[i] = {**msgs[i], "content": _dict_to_prompt(new_input)}
                    return msgs
            return msgs

    return [{"role": "user", "content": _dict_to_prompt(new_input)}]


def _dict_to_prompt(d: Dict[str, Any]) -> str:
    """
    Convert a dict of agent inputs into a prompt string.

    If the dict has a single string value, use it directly.
    Otherwise JSON-serialize the whole dict.
    """
    str_values = [v for v in d.values() if isinstance(v, str)]
    if len(d) == 1 and len(str_values) == 1:
        return str_values[0]
    return json.dumps(d, indent=2, default=str)


# ---------------------------------------------------------------------------
# Cost estimation (self-contained, no SDK dependency)
# ---------------------------------------------------------------------------


def _estimate_cost(model: Optional[str], usage: Dict[str, Optional[int]]) -> float:
    """Estimate USD cost from model name and token usage."""
    if not model:
        return 0.0
    m = model.lower()
    for key, (inp_price, out_price) in _COST_PER_MILLION.items():
        if key in m:
            in_m = (usage.get("prompt_tokens") or 0) / 1_000_000
            out_m = (usage.get("completion_tokens") or 0) / 1_000_000
            return round(in_m * inp_price + out_m * out_price, 8)
    return 0.0


# ---------------------------------------------------------------------------
# ClickHouse helpers
# ---------------------------------------------------------------------------


def _fetch_span(
    client: Any, db: str, trace_id: str, span_id: str,
    *, workspace_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Fetch a single span row as a dict, scoped by workspace."""
    sql = (
        f"SELECT span_id, name, span_type, model, input, output, "
        f"latency_ms, cost_usd, total_tokens, error, "
        f"prompt_tokens, completion_tokens "
        f"FROM {db}.spans "
        f"WHERE trace_id = {{tid:String}} AND span_id = {{sid:String}} "
    )
    params: Dict[str, Any] = {"tid": trace_id, "sid": span_id}
    if workspace_id:
        sql += "AND workspace_id = {_ws:String} "
        params["_ws"] = workspace_id
    sql += "LIMIT 1"
    result = client.query(sql, parameters=params)
    if not result.result_rows:
        return None
    r = result.result_rows[0]
    return {
        "span_id": r[0], "name": r[1], "span_type": r[2], "model": r[3],
        "input": r[4], "output": r[5], "latency_ms": r[6], "cost_usd": r[7],
        "total_tokens": r[8], "error": r[9],
        "prompt_tokens": r[10], "completion_tokens": r[11],
    }


def _fetch_span_full(
    client: Any, db: str, trace_id: str, span_id: str,
    *, workspace_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Fetch a span row with parent_span_id and is_replay flag, scoped by workspace."""
    sql = (
        f"SELECT span_id, name, span_type, model, input, output, "
        f"latency_ms, cost_usd, total_tokens, error, "
        f"prompt_tokens, completion_tokens, parent_span_id, is_replay "
        f"FROM {db}.spans "
        f"WHERE trace_id = {{tid:String}} AND span_id = {{sid:String}} "
    )
    params: Dict[str, Any] = {"tid": trace_id, "sid": span_id}
    if workspace_id:
        sql += "AND workspace_id = {_ws:String} "
        params["_ws"] = workspace_id
    sql += "LIMIT 1"
    result = client.query(sql, parameters=params)
    if not result.result_rows:
        return None
    r = result.result_rows[0]
    return {
        "span_id": r[0], "name": r[1], "span_type": r[2], "model": r[3],
        "input": r[4], "output": r[5], "latency_ms": r[6], "cost_usd": r[7],
        "total_tokens": r[8], "error": r[9],
        "prompt_tokens": r[10], "completion_tokens": r[11],
        "parent_span_id": r[12], "is_replay": bool(r[13]),
    }


def _fetch_trace_span_lookup(
    client: Any, db: str, trace_id: str,
) -> Dict[str, Any]:
    """
    Fetch all spans for a trace in one query and return a lookup dict.

    Replaces per-span queries in parent-chain traversal (eliminates N+1).
    Returns: {span_id: {span_id, parent_span_id, name, span_type, input, output, decision}}
    """
    sql = (
        f"SELECT span_id, parent_span_id, name, span_type, input, output, decision "
        f"FROM {db}.spans "
        f"WHERE trace_id = {{tid:String}}"
    )
    result = client.query(sql, parameters={"tid": trace_id})
    return {
        r[0]: {
            "span_id": r[0],
            "parent_span_id": r[1],
            "name": r[2],
            "span_type": r[3],
            "input": r[4],
            "output": r[5],
            "decision": r[6],
        }
        for r in result.result_rows
    }


def _reconstruct_parent_context(
    client: Any, db: str, trace_id: str, parent_span_id: Optional[str],
    span_lookup: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Walk up the parent chain to reconstruct the execution context
    that was active when the child span originally ran.

    Uses a pre-fetched span_lookup dict to avoid N+1 ClickHouse queries.
    Falls back to single-span queries only when span_lookup is not provided.

    Returns a dict with "chain" (list of ancestor span summaries)
    for injection into the replay LLM call, or None if root span.
    """
    if not parent_span_id:
        return None

    lookup = span_lookup or _fetch_trace_span_lookup(client, db, trace_id)

    chain: List[Dict[str, Any]] = []
    visited: set = set()
    current_id = parent_span_id

    while current_id and current_id not in visited:
        visited.add(current_id)
        r = lookup.get(current_id)
        if not r:
            break
        chain.append({
            "span_id": r["span_id"],
            "name": r["name"],
            "span_type": r["span_type"],
            "input_summary": _truncate_for_context(_parse_json_field(r["input"])),
            "output_summary": _truncate_for_context(_parse_json_field(r["output"])),
            "decision": r["decision"],
        })
        current_id = r["parent_span_id"]

    if not chain:
        return None

    chain.reverse()
    return {"chain": chain}


def _compute_tree_position(
    client: Any, db: str, trace_id: str, span_id: str, parent_span_id: Optional[str],
    span_lookup: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute the span's position in the tree for the side-by-side diff view.

    Uses a pre-fetched span_lookup dict to avoid N+1 ClickHouse queries.
    """
    lookup = span_lookup or _fetch_trace_span_lookup(client, db, trace_id)

    depth = 0
    current_id = parent_span_id
    visited: set = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        depth += 1
        r = lookup.get(current_id)
        if not r:
            break
        current_id = r["parent_span_id"]

    sibling_count = sum(
        1 for r in lookup.values()
        if r["parent_span_id"] == parent_span_id and r["span_id"] != span_id
    ) + 1 if parent_span_id else 0

    return {
        "depth": depth,
        "parent_span_id": parent_span_id,
        "is_root": parent_span_id is None,
        "sibling_count": sibling_count,
    }


def _truncate_for_context(value: Any, max_len: int = 500) -> Optional[str]:
    """Truncate a value to a short string suitable for context injection."""
    if value is None:
        return None
    s = json.dumps(value, default=str) if not isinstance(value, str) else value
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


def _format_parent_context(parent_context: Dict[str, Any]) -> str:
    """Format parent chain into a system message for the replay LLM call."""
    chain = parent_context.get("chain", [])
    if not chain:
        return ""
    lines = ["[VerdictLens Replay] Parent execution context:"]
    for i, ancestor in enumerate(chain):
        lines.append(f"\n--- Ancestor {i + 1}: {ancestor['name']} ({ancestor['span_type']}) ---")
        if ancestor.get("decision"):
            lines.append(f"Decision: {ancestor['decision']}")
        if ancestor.get("input_summary"):
            lines.append(f"Input: {ancestor['input_summary']}")
        if ancestor.get("output_summary"):
            lines.append(f"Output: {ancestor['output_summary']}")
    lines.append("\n--- Replaying child span below with this context ---")
    return "\n".join(lines)


def _fetch_span_field(
    client: Any, db: str, span_id: str, field: str,
    *, workspace_id: str = "",
) -> Any:
    """Fetch a single column value from a span, optionally scoped by workspace."""
    sql = f"SELECT {field} FROM {db}.spans WHERE span_id = {{sid:String}} "
    params: Dict[str, Any] = {"sid": span_id}
    if workspace_id:
        sql += "AND workspace_id = {_ws:String} "
        params["_ws"] = workspace_id
    sql += "LIMIT 1"
    result = client.query(sql, parameters=params)
    if not result.result_rows:
        return None
    return result.result_rows[0][0]



def _store_replay_span(
    *,
    client: Any,
    db: str,
    replay_span_id: str,
    original_span_id: str,
    trace_id: str,
    name: str,
    span_type: str,
    model: Optional[str],
    parent_span_id: Optional[str] = None,
    new_input: Dict[str, Any],
    new_output: Any,
    new_error: Any,
    latency_ms: float,
    cost_usd: float,
    total_tokens: int,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    note: Optional[str],
    status: str,
    now: datetime,
    workspace_id: str = "default",
) -> None:
    """Insert a replay span row into ClickHouse, preserving tree position."""
    from datetime import timedelta
    error_json = _safe_json(new_error) if new_error else None
    start_time = now - timedelta(milliseconds=latency_ms)

    row = [
        replay_span_id,
        parent_span_id,
        trace_id,
        name,
        span_type,
        start_time,             # start_time = end_time - latency
        now,                    # end_time
        latency_ms,
        model,
        _safe_json(new_input),
        _safe_json(new_output),
        None,                   # decision
        None,                   # confidence_score
        prompt_tokens,
        completion_tokens,
        total_tokens,
        cost_usd,
        error_json,
        _safe_json({"replay_status": status, "original_span_id": original_span_id}),
        now,                    # inserted_at
        True,                   # is_replay
        original_span_id,
        note,
        workspace_id,
    ]

    client.insert(
        f"{db}.spans",
        [row],
        column_names=[
            "span_id", "parent_span_id", "trace_id", "name", "span_type",
            "start_time", "end_time", "latency_ms", "model", "input", "output",
            "decision", "confidence_score",
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cost_usd", "error", "metadata", "inserted_at",
            "is_replay", "original_span_id", "replay_note",
            "workspace_id",
        ],
    )
    logger.info(
        "verdictlens: stored replay %s for original %s (status=%s)",
        replay_span_id, original_span_id, status,
    )


# ---------------------------------------------------------------------------
# SBFL suspiciousness scoring (arXiv 2405.00565 — SBFL without fault-triggering tests)
# ---------------------------------------------------------------------------


def _compute_suspiciousness(
    original_output: Any,
    new_output: Any,
    original_error: Any,
    new_error: Any,
    status: str,
) -> float:
    """
    SBFL-inspired suspiciousness score: how likely is this span to be the root cause?

    Logic mirrors spectrum-based fault localization — spans that appear in failing
    runs but not in passing runs are more suspicious. Here we approximate this by
    comparing output deviation between the original (failing) and replay runs:

    - original had error, replay fixed it  → confirmed originator (1.0)
    - both runs error                      → confirmed faulty span (0.9)
    - outputs identical                    → stable, low suspicion (0.1)
    - outputs differ without error         → suspicious by edit-distance (0.2–0.8)

    :returns: Suspiciousness score in [0.0, 1.0].
    """
    orig_had_error = original_error is not None
    new_has_error = new_error is not None

    if orig_had_error and not new_has_error and new_output is not None:
        return 1.0
    if orig_had_error and new_has_error:
        return 0.9
    if status == "same":
        return 0.1

    import difflib as _dl

    orig_str = json.dumps(original_output, default=str) if original_output is not None else ""
    new_str = json.dumps(new_output, default=str) if new_output is not None else ""
    if not orig_str and not new_str:
        return 0.1
    longer = max(len(orig_str), len(new_str))
    if longer == 0:
        return 0.1
    similarity = _dl.SequenceMatcher(None, orig_str, new_str).ratio()
    # Low similarity = large change = high suspicion (capped at 0.8 for non-error cases)
    return round(max(0.1, min(0.8, 1.0 - similarity)), 4)


# ---------------------------------------------------------------------------
# Diff / status helpers
# ---------------------------------------------------------------------------


def _compute_status(
    original_output: Any,
    new_output: Any,
    original_error: Any,
    new_error: Any,
) -> Literal["same", "improved", "degraded", "different"]:
    """Determine replay outcome by comparing outputs and errors."""
    orig_had_error = original_error is not None
    new_has_error = new_error is not None

    if new_has_error and not orig_had_error:
        return "degraded"
    if orig_had_error and not new_has_error and new_output is not None:
        return "improved"

    orig_json = json.dumps(original_output, sort_keys=True, default=str)
    new_json = json.dumps(new_output, sort_keys=True, default=str)

    if orig_json == new_json:
        return "same"
    return "different"


def _compute_improvement(
    status: str,
    orig_latency: float,
    new_latency: float,
    orig_cost: float,
    new_cost: float,
) -> Optional[float]:
    """Compute an improvement score (0.0 to 1.0)."""
    if status == "improved":
        return 1.0
    if status == "degraded":
        return 0.0
    if status == "same":
        return 0.5

    score = 0.5
    if orig_latency > 0 and new_latency > 0:
        if new_latency < orig_latency:
            score += 0.15
        elif new_latency > orig_latency:
            score -= 0.15
    if orig_cost > 0 and new_cost > 0:
        if new_cost < orig_cost:
            score += 0.1
        elif new_cost > orig_cost:
            score -= 0.1

    return max(0.0, min(1.0, round(score, 2)))


def _compute_diff(original_output: Any, new_output: Any) -> List[str]:
    """Compute a human-readable unified diff between original and new output."""
    orig_str = json.dumps(original_output, indent=2, sort_keys=True, default=str)
    new_str = json.dumps(new_output, indent=2, sort_keys=True, default=str)

    diff = difflib.unified_diff(
        orig_str.splitlines(),
        new_str.splitlines(),
        fromfile="original",
        tofile="replay",
        lineterm="",
    )
    return list(diff)
