"""
OpenAI client instrumentation (``openai`` package).

Patches chat completion ``create`` methods on a client instance to emit traces.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, Callable, Optional

from verdictlens.pricing import estimate_cost_usd
from verdictlens.serializers import extract_openai_usage, safe_serialize
from verdictlens.trace import emit_trace
from verdictlens.types import SpanRecord, TokenUsage, TraceEvent, utc_now_iso


def _latency_ms(t0: float) -> float:
    """
    Milliseconds elapsed since ``t0`` (perf_counter).

    :param t0: Start time from :func:`time.perf_counter`.
    :returns: Elapsed milliseconds rounded to 3 decimals.
    """
    return round((time.perf_counter() - t0) * 1000.0, 3)


def _trace_from_response(
    *,
    name: str,
    kwargs: dict[str, Any],
    response: Any,
    error: Optional[str],
    start_wall: str,
    end_wall: str,
    latency_ms: float,
) -> None:
    """
    Build and emit a trace for a single OpenAI chat completion call.

    :param name: Trace/span name.
    :param kwargs: Original ``create`` keyword arguments.
    :param response: Provider response object (if successful).
    :param error: Error string (if failed).
    :param start_wall: ISO start timestamp.
    :param end_wall: ISO end timestamp.
    :param latency_ms: Latency in milliseconds.
    :returns: None
    """
    model = None
    if error is None and response is not None:
        model = getattr(response, "model", None) or kwargs.get("model")
        model = str(model) if model is not None else None
    elif kwargs.get("model") is not None:
        model = str(kwargs.get("model"))

    usage_dict = extract_openai_usage(getattr(response, "usage", None)) if response is not None else None
    tu = (
        TokenUsage(
            prompt_tokens=usage_dict.get("prompt_tokens") if usage_dict else None,
            completion_tokens=usage_dict.get("completion_tokens") if usage_dict else None,
            total_tokens=usage_dict.get("total_tokens") if usage_dict else None,
        )
        if usage_dict
        else None
    )
    cost = estimate_cost_usd(model, usage_dict or {}) if usage_dict else None

    input_payload = {
        "messages": safe_serialize(kwargs.get("messages")),
        "model": safe_serialize(kwargs.get("model")),
        "temperature": safe_serialize(kwargs.get("temperature")),
    }

    output_payload = safe_serialize(response) if error is None else None

    span = SpanRecord(
        name=name,
        span_type="llm",
        start_time=start_wall,
        end_time=end_wall,
        latency_ms=latency_ms,
        model=model,
        input=input_payload,
        output=output_payload,
        token_usage=tu,
        cost_usd=cost,
        error=error,
        metadata={"integration": "openai"},
    )

    event = TraceEvent(
        name=name,
        start_time=start_wall,
        end_time=end_wall,
        latency_ms=latency_ms,
        status="error" if error else "ok",
        framework="openai",
        model=model,
        input=input_payload,
        output=output_payload,
        token_usage=tu,
        cost_usd=cost,
        error=error,
        spans=[span],
    )
    emit_trace(event)


def _wrap_sync_create(orig: Callable[..., Any], trace_name: str) -> Callable[..., Any]:
    """
    Wrap a synchronous ``create`` method.

    :param orig: Original bound method.
    :param trace_name: Trace name prefix.
    :returns: Wrapped callable.
    """

    def _inner(*args: Any, **kwargs: Any) -> Any:
        """
        Traced synchronous OpenAI completion call.

        :param args: Forwarded positional args.
        :param kwargs: Forwarded keyword args.
        :returns: Original method result.
        """
        start_wall = utc_now_iso()
        t0 = time.perf_counter()
        err: Optional[str] = None
        response: Any = None
        try:
            response = orig(*args, **kwargs)
            return response
        except BaseException as exc:
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            end_wall = utc_now_iso()
            _trace_from_response(
                name=trace_name,
                kwargs=dict(kwargs),
                response=response,
                error=err,
                start_wall=start_wall,
                end_wall=end_wall,
                latency_ms=_latency_ms(t0),
            )

    return _inner


def _wrap_async_create(orig: Callable[..., Any], trace_name: str) -> Callable[..., Any]:
    """
    Wrap an async ``create`` method.

    :param orig: Original bound method.
    :param trace_name: Trace name prefix.
    :returns: Wrapped coroutine function.
    """

    async def _inner(*args: Any, **kwargs: Any) -> Any:
        """
        Traced asynchronous OpenAI completion call.

        :param args: Forwarded positional args.
        :param kwargs: Forwarded keyword args.
        :returns: Original method awaitable result.
        """
        start_wall = utc_now_iso()
        t0 = time.perf_counter()
        err: Optional[str] = None
        response: Any = None
        try:
            response = await orig(*args, **kwargs)
            return response
        except BaseException as exc:
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            end_wall = utc_now_iso()
            _trace_from_response(
                name=trace_name,
                kwargs=dict(kwargs),
                response=response,
                error=err,
                start_wall=start_wall,
                end_wall=end_wall,
                latency_ms=_latency_ms(t0),
            )

    return _inner


def instrument_openai_client(client: Any) -> Any:
    """
    Monkey-patch a client's chat completion ``create`` to emit VerdictLens traces.

    :param client: An ``openai.OpenAI`` or ``openai.AsyncOpenAI`` instance.
    :returns: The same client instance.
    :raises ImportError: If the ``openai`` package is not installed.
    """
    try:
        import openai  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError("verdictlens OpenAI integration requires `pip install openai`") from exc

    if getattr(client, "_verdictlens_openai_patched", False):
        return client

    chat = getattr(client, "chat", None)
    completions = getattr(chat, "completions", None) if chat is not None else None
    if completions is None:
        raise TypeError("client.chat.completions is required for OpenAI instrumentation")

    orig_create = completions.create
    trace_name = f"openai.chat.completions:{getattr(client, 'base_url', 'default')}"

    if inspect.iscoroutinefunction(orig_create):
        completions.create = _wrap_async_create(orig_create, trace_name)
    else:
        completions.create = _wrap_sync_create(orig_create, trace_name)

    setattr(client, "_verdictlens_openai_patched", True)
    return client
