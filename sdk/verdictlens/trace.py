"""
``@trace`` decorator with hierarchical span context propagation.

Uses ``contextvars`` to maintain a span stack. When ``@trace`` is called
inside another ``@trace``, the inner call becomes a child span of the outer.
The outermost ``@trace`` creates the root span and emits the full trace
envelope with all accumulated child spans.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import sys
import time
import traceback as _tb
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar, Union, cast, overload
from uuid import uuid4

from verdictlens.client import get_client
from verdictlens.config import get_config
from verdictlens.pricing import estimate_cost_usd
from verdictlens.serializers import safe_serialize
from verdictlens.types import SpanRecord, TokenUsage, TraceEvent, utc_now_iso

F = TypeVar("F", bound=Callable[..., Any])

_active_span: contextvars.ContextVar[Optional["_SpanContext"]] = contextvars.ContextVar(
    "verdictlens_active_span", default=None,
)

# Trace-level data-flow registry — maps id(object) → span_id.
# Populated when a span's return value is registered, read when the
# next span starts to detect which upstream span produced this input.
_output_registry: contextvars.ContextVar[Optional[Dict[int, str]]] = contextvars.ContextVar(
    "verdictlens_output_registry", default=None,
)
# Strong references that prevent GC from recycling object ids before the
# trace completes (important for strings and other short-lived values).
_output_refs: contextvars.ContextVar[Optional[List[Any]]] = contextvars.ContextVar(
    "verdictlens_output_refs", default=None,
)


class _SpanContext:
    """Mutable context for a span being recorded."""

    __slots__ = (
        "span_id", "parent_span_id", "trace_id", "name", "span_type",
        "framework", "model", "decision", "confidence_score",
        "start_wall", "t0", "children", "source_span_ids",
    )

    def __init__(
        self,
        *,
        name: str,
        span_type: str,
        framework: Optional[str],
        model: Optional[str],
        decision: Optional[str],
        parent: Optional["_SpanContext"],
    ) -> None:
        self.span_id = str(uuid4())
        self.parent_span_id = parent.span_id if parent else None
        self.trace_id = parent.trace_id if parent else str(uuid4())
        self.name = name
        self.span_type = span_type
        self.framework = framework
        self.model = model
        self.decision = decision
        self.confidence_score: Optional[float] = None
        self.start_wall = utc_now_iso()
        self.t0 = time.perf_counter() * 1000.0
        self.children: List[SpanRecord] = []
        self.source_span_ids: List[str] = []

    @property
    def is_root(self) -> bool:
        return self.parent_span_id is None


def get_current_span() -> Optional[_SpanContext]:
    """Return the active span context, or None if no trace is active."""
    return _active_span.get()


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _build_token_usage(raw: Optional[Dict[str, Optional[int]]]) -> Optional[TokenUsage]:
    if not raw:
        return None
    if all(raw.get(k) is None for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
        return None
    return TokenUsage(
        prompt_tokens=raw.get("prompt_tokens"),
        completion_tokens=raw.get("completion_tokens"),
        total_tokens=raw.get("total_tokens"),
    )


def _extract_usage_from_result(result: Any) -> Optional[Dict[str, Optional[int]]]:
    if result is None:
        return None
    candidates = []
    if isinstance(result, dict):
        candidates.append(result.get("usage"))
        candidates.append(result.get("token_usage"))
    else:
        candidates.append(getattr(result, "usage", None))
        candidates.append(getattr(result, "token_usage", None))
    for usage in candidates:
        if usage is None:
            continue
        if isinstance(usage, dict):
            return {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        pt = getattr(usage, "prompt_tokens", None)
        ct = getattr(usage, "completion_tokens", None)
        tt = getattr(usage, "total_tokens", None)
        try:
            return {
                "prompt_tokens": int(pt) if pt is not None else None,
                "completion_tokens": int(ct) if ct is not None else None,
                "total_tokens": int(tt) if tt is not None else None,
            }
        except Exception:
            continue
    return None


def _extract_model_from_result(result: Any) -> Optional[str]:
    if result is None:
        return None
    if isinstance(result, dict):
        m = result.get("model")
        return str(m) if m is not None else None
    m = getattr(result, "model", None)
    return str(m) if m is not None else None


def _extract_decision_from_result(result: Any) -> Optional[str]:
    if result is None:
        return None
    if isinstance(result, dict):
        d = result.get("decision")
        return str(d) if d is not None else None
    d = getattr(result, "decision", None)
    return str(d) if d is not None else None


def _extract_confidence_from_result(result: Any) -> Optional[float]:
    if result is None:
        return None
    raw = None
    if isinstance(result, dict):
        raw = result.get("confidence_score") or result.get("confidence")
    else:
        raw = getattr(result, "confidence_score", None) or getattr(result, "confidence", None)
    if raw is None:
        return None
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return None


def _make_error_dict(exc: BaseException) -> Dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "stack": _tb.format_exc(),
    }


def emit_trace(trace: TraceEvent) -> None:
    cfg = get_config()
    if cfg.disabled:
        return
    try:
        payload = trace.model_dump(mode="json")
    except Exception as exc:
        get_client().send_trace(
            {
                "trace_id": trace.trace_id,
                "name": trace.name,
                "status": "error",
                "error": {"type": "SerializeError", "message": str(exc), "stack": None},
                "metadata": {"sdk": "verdictlens", "serialize_error": True},
            }
        )
        return
    payload.setdefault("metadata", {})
    meta = payload["metadata"]
    if isinstance(meta, dict):
        meta.setdefault("sdk", "verdictlens")
        meta.setdefault("python", sys.version.split()[0])
        meta.setdefault("schema_version", "2.0.0")
    get_client().send_trace(payload)


# ---------------------------------------------------------------------------
# Public decorator
# ---------------------------------------------------------------------------

@overload
def trace(
    func: F,
    *,
    name: Optional[str] = None,
    span_type: str = "agent",
    framework: Optional[str] = None,
    model: Optional[str] = None,
    decision: Optional[str] = None,
    capture_args: bool = True,
    capture_result: bool = True,
) -> F: ...


@overload
def trace(
    func: None = None,
    *,
    name: Optional[str] = None,
    span_type: str = "agent",
    framework: Optional[str] = None,
    model: Optional[str] = None,
    decision: Optional[str] = None,
    capture_args: bool = True,
    capture_result: bool = True,
) -> Callable[[F], F]: ...


def trace(
    func: Optional[F] = None,
    *,
    name: Optional[str] = None,
    span_type: str = "agent",
    framework: Optional[str] = None,
    model: Optional[str] = None,
    decision: Optional[str] = None,
    capture_args: bool = True,
    capture_result: bool = True,
) -> Union[F, Callable[[F], F]]:
    """
    Decorate a sync or async callable to record a span.

    If called inside another ``@trace``-decorated function, the span
    automatically becomes a child of the outer span. The outermost
    ``@trace`` emits the full trace with all nested spans.

    Works correctly across ``asyncio.gather`` and thread boundaries
    via ``contextvars``.
    """

    def decorator(fn: F) -> F:
        qual = name or f"{fn.__module__}:{fn.__qualname__}"

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await _run_traced_async(
                    fn, qual,
                    span_type=span_type,
                    framework=framework,
                    static_model=model,
                    static_decision=decision,
                    capture_args=capture_args,
                    capture_result=capture_result,
                    args=args, kwargs=kwargs,
                )

            return cast(F, async_wrapper)

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return _run_traced_sync(
                fn, qual,
                span_type=span_type,
                framework=framework,
                static_model=model,
                static_decision=decision,
                capture_args=capture_args,
                capture_result=capture_result,
                args=args, kwargs=kwargs,
            )

        return cast(F, sync_wrapper)

    if func is None:
        return decorator
    return decorator(cast(F, func))


# ---------------------------------------------------------------------------
# Data-flow lineage helpers
# ---------------------------------------------------------------------------

def _should_track_lineage(obj: Any) -> bool:
    """
    Return True for objects whose identity (id()) is stable and meaningful.

    Primitives (bool, int, float) are excluded — they are heavily interned
    by CPython and id() is unreliable across spans.  Short strings are also
    excluded to avoid false-positive matches on common values like "ok".
    None is a singleton and is tracked so that null-output propagation
    (a common failure mode in agent pipelines) is correctly attributed.
    """
    if obj is None:
        return True  # track None: singleton with stable id(), key failure sentinel
    if isinstance(obj, (bool, int, float)):
        return False
    if isinstance(obj, str):
        return len(obj) > 20
    return True  # dicts, lists, custom objects


def _detect_sources(args: tuple, kwargs: Dict[str, Any]) -> List[str]:
    """
    Walk top-level call arguments and return span_ids of any upstream spans
    whose outputs are being passed in as inputs to the current span.
    """
    registry = _output_registry.get()
    if not registry:
        return []
    seen: List[str] = []
    for val in (*args, *kwargs.values()):
        src = registry.get(id(val))
        if src and src not in seen:
            seen.append(src)
    return seen


def _register_output(result: Any, span_id: str) -> None:
    """
    Register a span's return value in the trace-level output registry so
    downstream spans can detect this data-flow dependency.
    """
    if not _should_track_lineage(result):
        return
    registry = _output_registry.get()
    refs = _output_refs.get()
    if registry is None or refs is None:
        return
    registry[id(result)] = span_id
    if result is not None:
        refs.append(result)  # keep alive — prevents CPython from recycling the id


def _propagate_bad_inputs(args: tuple, kwargs: Dict[str, Any], span_id: str) -> None:
    """
    When a span raises, re-register any of its tracked arguments under its
    own span_id.  This advances the chain so downstream spans that receive
    the same value attribute the failure to the closest failing span rather
    than the original root cause.

    Example: research returns None → None registered to research.
             planner(None) raises → None re-registered to planner.
             executor(None) → source_span_ids=[planner] (not research).
    """
    registry = _output_registry.get()
    if not registry:
        return
    for val in (*args, *kwargs.values()):
        if _should_track_lineage(val) and id(val) in registry:
            registry[id(val)] = span_id


# ---------------------------------------------------------------------------
# Execution helpers with context propagation
# ---------------------------------------------------------------------------

def _run_traced_sync(
    fn: Callable[..., Any],
    qual: str,
    *,
    span_type: str,
    framework: Optional[str],
    static_model: Optional[str],
    static_decision: Optional[str],
    capture_args: bool,
    capture_result: bool,
    args: tuple[Any, ...],
    kwargs: Dict[str, Any],
) -> Any:
    parent = _active_span.get()
    ctx = _SpanContext(
        name=qual,
        span_type=span_type,
        framework=framework,
        model=static_model,
        decision=static_decision,
        parent=parent,
    )

    # Root span: initialize the trace-level output registry
    reg_token = None
    refs_token = None
    if parent is None:
        reg_token = _output_registry.set({})
        refs_token = _output_refs.set([])

    # Detect which upstream span's output is being passed in as input
    ctx.source_span_ids = _detect_sources(args, kwargs)

    token = _active_span.set(ctx)
    err_dict: Optional[Dict[str, Any]] = None
    result: Any = None
    try:
        result = fn(*args, **kwargs)
        return result
    except BaseException as exc:
        err_dict = _make_error_dict(exc)
        raise
    finally:
        _active_span.reset(token)
        t1 = _now_ms()
        end_wall = utc_now_iso()
        if err_dict is None:
            _register_output(result, ctx.span_id)
        else:
            # Advance the chain: any tracked arg now attributed to this span
            _propagate_bad_inputs(args, kwargs, ctx.span_id)
        _finalize_span(
            ctx=ctx,
            parent=parent,
            capture_args=capture_args,
            capture_result=capture_result,
            args=args,
            kwargs=kwargs,
            result=result if err_dict is None else None,
            error=err_dict,
            end_wall=end_wall,
            latency_ms=t1 - ctx.t0,
        )
        # Root span cleanup: drop registry so GC can reclaim objects
        if reg_token is not None:
            _output_registry.reset(reg_token)
        if refs_token is not None:
            _output_refs.reset(refs_token)


async def _run_traced_async(
    fn: Callable[..., Awaitable[Any]],
    qual: str,
    *,
    span_type: str,
    framework: Optional[str],
    static_model: Optional[str],
    static_decision: Optional[str],
    capture_args: bool,
    capture_result: bool,
    args: tuple[Any, ...],
    kwargs: Dict[str, Any],
) -> Any:
    parent = _active_span.get()
    ctx = _SpanContext(
        name=qual,
        span_type=span_type,
        framework=framework,
        model=static_model,
        decision=static_decision,
        parent=parent,
    )

    # Root span: initialize the trace-level output registry
    reg_token = None
    refs_token = None
    if parent is None:
        reg_token = _output_registry.set({})
        refs_token = _output_refs.set([])

    # Detect which upstream span's output is being passed in as input
    ctx.source_span_ids = _detect_sources(args, kwargs)

    token = _active_span.set(ctx)
    err_dict: Optional[Dict[str, Any]] = None
    result: Any = None
    try:
        result = await fn(*args, **kwargs)
        return result
    except BaseException as exc:
        err_dict = _make_error_dict(exc)
        raise
    finally:
        _active_span.reset(token)
        t1 = _now_ms()
        end_wall = utc_now_iso()
        if err_dict is None:
            _register_output(result, ctx.span_id)
        else:
            # Advance the chain: any tracked arg now attributed to this span
            _propagate_bad_inputs(args, kwargs, ctx.span_id)
        _finalize_span(
            ctx=ctx,
            parent=parent,
            capture_args=capture_args,
            capture_result=capture_result,
            args=args,
            kwargs=kwargs,
            result=result if err_dict is None else None,
            error=err_dict,
            end_wall=end_wall,
            latency_ms=t1 - ctx.t0,
        )
        # Root span cleanup: drop registry so GC can reclaim objects
        if reg_token is not None:
            _output_registry.reset(reg_token)
        if refs_token is not None:
            _output_refs.reset(refs_token)


def _finalize_span(
    *,
    ctx: _SpanContext,
    parent: Optional[_SpanContext],
    capture_args: bool,
    capture_result: bool,
    args: tuple[Any, ...],
    kwargs: Dict[str, Any],
    result: Any,
    error: Optional[Dict[str, Any]],
    end_wall: str,
    latency_ms: float,
) -> None:
    usage_dict = _extract_usage_from_result(result) if error is None else None
    resolved_model = ctx.model or (_extract_model_from_result(result) if error is None else None)
    cost = estimate_cost_usd(resolved_model, usage_dict or {}) if usage_dict else None

    resolved_decision = ctx.decision or (_extract_decision_from_result(result) if error is None else None)
    confidence = _extract_confidence_from_result(result) if error is None else None

    span = SpanRecord(
        span_id=ctx.span_id,
        parent_span_id=ctx.parent_span_id,
        name=ctx.name,
        span_type=ctx.span_type,
        start_time=ctx.start_wall,
        end_time=end_wall,
        latency_ms=round(latency_ms, 3),
        model=resolved_model,
        input={"args": safe_serialize(args), "kwargs": safe_serialize(kwargs)} if capture_args else None,
        output=safe_serialize(result) if capture_result and error is None else None,
        decision=resolved_decision,
        confidence_score=confidence,
        token_usage=_build_token_usage(usage_dict),
        cost_usd=cost,
        error=error,
        metadata={"span_role": "root" if ctx.is_root else "child"},
        source_span_ids=ctx.source_span_ids,
    )

    if parent is not None:
        parent.children.append(span)
        for child in ctx.children:
            parent.children.append(child)
    else:
        all_spans = [span] + ctx.children
        _emit_root_trace(
            ctx=ctx,
            root_span=span,
            all_spans=all_spans,
            framework=ctx.framework,
            error=error,
        )


def _emit_root_trace(
    *,
    ctx: _SpanContext,
    root_span: SpanRecord,
    all_spans: List[SpanRecord],
    framework: Optional[str],
    error: Optional[Dict[str, Any]],
) -> None:
    any_error = error is not None or any(s.error is not None for s in all_spans)
    status = "error" if any_error else "success"

    agg_model, agg_usage, agg_cost = _aggregate_from_spans(all_spans)
    resolved_model = root_span.model or agg_model
    resolved_usage = root_span.token_usage or agg_usage
    resolved_cost = root_span.cost_usd if root_span.cost_usd is not None else agg_cost

    event = TraceEvent(
        trace_id=ctx.trace_id,
        name=ctx.name,
        start_time=root_span.start_time,
        end_time=root_span.end_time,
        latency_ms=root_span.latency_ms,
        status=status,
        framework=framework,
        model=resolved_model,
        input=root_span.input,
        output=root_span.output,
        decision=root_span.decision,
        confidence_score=root_span.confidence_score,
        token_usage=resolved_usage,
        cost_usd=resolved_cost,
        error=error,
        spans=all_spans,
    )
    emit_trace(event)


def _aggregate_from_spans(
    spans: List[SpanRecord],
) -> tuple[Optional[str], Optional[TokenUsage], Optional[float]]:
    """
    Aggregate model, token_usage, and cost from all child spans
    so the trace-level header shows meaningful totals.
    """
    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    total_cost = 0.0
    has_usage = False
    has_cost = False
    models: List[str] = []

    for s in spans:
        if s.model and s.model not in models:
            models.append(s.model)
        if s.token_usage is not None:
            has_usage = True
            total_prompt += s.token_usage.prompt_tokens or 0
            total_completion += s.token_usage.completion_tokens or 0
            total_tokens += s.token_usage.total_tokens or 0
        if s.cost_usd is not None:
            has_cost = True
            total_cost += s.cost_usd

    agg_model: Optional[str] = None
    if len(models) == 1:
        agg_model = models[0]
    elif models:
        agg_model = models[0]

    agg_usage: Optional[TokenUsage] = None
    if has_usage:
        agg_usage = TokenUsage(
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            total_tokens=total_tokens,
        )

    agg_cost: Optional[float] = round(total_cost, 8) if has_cost else None

    return agg_model, agg_usage, agg_cost


# ---------------------------------------------------------------------------
# Utility: create a child span programmatically (for auto-patchers)
# ---------------------------------------------------------------------------

def record_child_span(
    *,
    name: str,
    span_type: str = "llm",
    model: Optional[str] = None,
    input_data: Optional[Any] = None,
    output_data: Optional[Any] = None,
    error: Optional[Dict[str, Any]] = None,
    latency_ms: float = 0.0,
    token_usage: Optional[Dict[str, Optional[int]]] = None,
    cost_usd: Optional[float] = None,
) -> Optional[str]:
    """
    Programmatically add a child span under the active trace context.

    Used by auto-patchers (wrap_openai, wrap_anthropic) to record LLM
    calls without requiring ``@trace`` on every call site.

    Returns the span_id, or None if no active trace context.
    """
    parent = _active_span.get()
    if parent is None:
        return None

    span_id = str(uuid4())
    now = utc_now_iso()

    span = SpanRecord(
        span_id=span_id,
        parent_span_id=parent.span_id,
        name=name,
        span_type=span_type,
        start_time=now,
        end_time=now,
        latency_ms=round(latency_ms, 3),
        model=model,
        input=safe_serialize(input_data) if input_data is not None else None,
        output=safe_serialize(output_data) if output_data is not None else None,
        token_usage=_build_token_usage(token_usage),
        cost_usd=cost_usd,
        error=error,
        metadata={"span_role": "auto"},
    )

    parent.children.append(span)
    return span_id
