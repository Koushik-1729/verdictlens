"""
Auto-patchers for LLM client libraries.

Usage::

    from openai import OpenAI
    from verdictlens.patchers import wrap_openai

    client = wrap_openai(OpenAI())

Any call to ``client.chat.completions.create(...)`` inside a ``@trace``
context will automatically record a child span with model, tokens, cost,
and latency — no extra decorator needed.

For Anthropic::

    from anthropic import Anthropic
    from verdictlens.patchers import wrap_anthropic

    client = wrap_anthropic(Anthropic())

For Google Gemini::

    from google import genai
    from verdictlens.patchers import wrap_google

    client = wrap_google(genai.Client(api_key="..."))
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Dict, Optional, TypeVar

from verdictlens.pricing import estimate_cost_usd
from verdictlens.serializers import safe_serialize
from verdictlens.trace import _active_span, record_child_span

T = TypeVar("T")


def wrap_openai(client: T) -> T:
    """
    Patch an OpenAI client so ``chat.completions.create`` auto-traces.

    Returns the same client instance (mutated in-place). Safe to call
    multiple times — the patch is idempotent.
    """
    chat_completions = getattr(getattr(client, "chat", None), "completions", None)
    if chat_completions is None:
        return client

    if getattr(chat_completions, "_verdictlens_patched", False):
        return client

    original_create = chat_completions.create
    is_async = _is_coroutine_func(original_create)

    if is_async:
        @functools.wraps(original_create)
        async def patched_create(*args: Any, **kwargs: Any) -> Any:
            if _active_span.get() is None:
                return await original_create(*args, **kwargs)
            return await _trace_openai_async(original_create, args, kwargs)

        chat_completions.create = patched_create
    else:
        @functools.wraps(original_create)
        def patched_create(*args: Any, **kwargs: Any) -> Any:
            if _active_span.get() is None:
                return original_create(*args, **kwargs)
            return _trace_openai_sync(original_create, args, kwargs)

        chat_completions.create = patched_create

    chat_completions._verdictlens_patched = True
    return client


def wrap_anthropic(client: T) -> T:
    """
    Patch an Anthropic client so ``messages.create`` auto-traces.

    Returns the same client instance (mutated in-place).
    """
    messages = getattr(client, "messages", None)
    if messages is None:
        return client

    if getattr(messages, "_verdictlens_patched", False):
        return client

    original_create = messages.create
    is_async = _is_coroutine_func(original_create)

    if is_async:
        @functools.wraps(original_create)
        async def patched_create(*args: Any, **kwargs: Any) -> Any:
            if _active_span.get() is None:
                return await original_create(*args, **kwargs)
            return await _trace_anthropic_async(original_create, args, kwargs)

        messages.create = patched_create
    else:
        @functools.wraps(original_create)
        def patched_create(*args: Any, **kwargs: Any) -> Any:
            if _active_span.get() is None:
                return original_create(*args, **kwargs)
            return _trace_anthropic_sync(original_create, args, kwargs)

        messages.create = patched_create

    messages._verdictlens_patched = True
    return client


# ---------------------------------------------------------------------------
# OpenAI tracing internals
# ---------------------------------------------------------------------------

def _trace_openai_sync(
    fn: Callable[..., Any], args: tuple, kwargs: Dict[str, Any],
) -> Any:
    model = kwargs.get("model") or "unknown"
    input_snapshot = _snapshot_openai_input(kwargs)

    t0 = time.perf_counter()
    error_dict: Optional[Dict[str, Any]] = None
    result: Any = None
    try:
        result = fn(*args, **kwargs)
        return result
    except BaseException as exc:
        error_dict = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _record_openai_span(model, input_snapshot, result, error_dict, latency_ms)


async def _trace_openai_async(
    fn: Callable[..., Any], args: tuple, kwargs: Dict[str, Any],
) -> Any:
    model = kwargs.get("model") or "unknown"
    input_snapshot = _snapshot_openai_input(kwargs)

    t0 = time.perf_counter()
    error_dict: Optional[Dict[str, Any]] = None
    result: Any = None
    try:
        result = await fn(*args, **kwargs)
        return result
    except BaseException as exc:
        error_dict = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _record_openai_span(model, input_snapshot, result, error_dict, latency_ms)


def _snapshot_openai_input(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    if "model" in kwargs:
        snap["model"] = kwargs["model"]
    if "messages" in kwargs:
        snap["messages"] = safe_serialize(kwargs["messages"])
    if "temperature" in kwargs:
        snap["temperature"] = kwargs["temperature"]
    if "max_tokens" in kwargs:
        snap["max_tokens"] = kwargs.get("max_tokens")
    return snap


def _record_openai_span(
    model: str,
    input_snapshot: Dict[str, Any],
    result: Any,
    error: Optional[Dict[str, Any]],
    latency_ms: float,
) -> None:
    output_data = None
    usage_dict: Optional[Dict[str, Optional[int]]] = None

    if result is not None and error is None:
        content = None
        try:
            content = result.choices[0].message.content
        except (AttributeError, IndexError):
            content = safe_serialize(result)
        output_data = {"role": "assistant", "content": content}

        usage = getattr(result, "usage", None)
        if usage is not None:
            usage_dict = {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }

    cost = estimate_cost_usd(model, usage_dict or {}) if usage_dict else None

    record_child_span(
        name=f"openai.chat.completions.create({model})",
        span_type="llm",
        model=model,
        input_data=input_snapshot,
        output_data=output_data,
        error=error,
        latency_ms=latency_ms,
        token_usage=usage_dict,
        cost_usd=cost,
    )


# ---------------------------------------------------------------------------
# Anthropic tracing internals
# ---------------------------------------------------------------------------

def _trace_anthropic_sync(
    fn: Callable[..., Any], args: tuple, kwargs: Dict[str, Any],
) -> Any:
    model = kwargs.get("model") or "unknown"
    input_snapshot = _snapshot_anthropic_input(kwargs)

    t0 = time.perf_counter()
    error_dict: Optional[Dict[str, Any]] = None
    result: Any = None
    try:
        result = fn(*args, **kwargs)
        return result
    except BaseException as exc:
        error_dict = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _record_anthropic_span(model, input_snapshot, result, error_dict, latency_ms)


async def _trace_anthropic_async(
    fn: Callable[..., Any], args: tuple, kwargs: Dict[str, Any],
) -> Any:
    model = kwargs.get("model") or "unknown"
    input_snapshot = _snapshot_anthropic_input(kwargs)

    t0 = time.perf_counter()
    error_dict: Optional[Dict[str, Any]] = None
    result: Any = None
    try:
        result = await fn(*args, **kwargs)
        return result
    except BaseException as exc:
        error_dict = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _record_anthropic_span(model, input_snapshot, result, error_dict, latency_ms)


def _snapshot_anthropic_input(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    if "model" in kwargs:
        snap["model"] = kwargs["model"]
    if "messages" in kwargs:
        snap["messages"] = safe_serialize(kwargs["messages"])
    if "system" in kwargs:
        snap["system"] = safe_serialize(kwargs["system"])
    if "max_tokens" in kwargs:
        snap["max_tokens"] = kwargs["max_tokens"]
    if "temperature" in kwargs:
        snap["temperature"] = kwargs["temperature"]
    return snap


def _record_anthropic_span(
    model: str,
    input_snapshot: Dict[str, Any],
    result: Any,
    error: Optional[Dict[str, Any]],
    latency_ms: float,
) -> None:
    output_data = None
    usage_dict: Optional[Dict[str, Optional[int]]] = None

    if result is not None and error is None:
        content = None
        try:
            content_blocks = result.content
            texts = [b.text for b in content_blocks if hasattr(b, "text")]
            content = "\n".join(texts) if texts else safe_serialize(result)
        except (AttributeError, TypeError):
            content = safe_serialize(result)
        output_data = {"role": "assistant", "content": content}

        usage = getattr(result, "usage", None)
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            usage_dict = {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": (
                    (input_tokens or 0) + (output_tokens or 0)
                    if input_tokens is not None or output_tokens is not None
                    else None
                ),
            }

    cost = estimate_cost_usd(model, usage_dict or {}) if usage_dict else None

    record_child_span(
        name=f"anthropic.messages.create({model})",
        span_type="llm",
        model=model,
        input_data=input_snapshot,
        output_data=output_data,
        error=error,
        latency_ms=latency_ms,
        token_usage=usage_dict,
        cost_usd=cost,
    )


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------


def wrap_google(client: T) -> T:
    """
    Patch a ``google.genai.Client`` so ``models.generate_content`` auto-traces.

    Patches both ``client.models`` (sync) and ``client.aio.models`` (async)
    when available.  Returns the same client instance (mutated in-place).
    """
    _patch_google_models(getattr(client, "models", None), is_async=False)
    aio = getattr(client, "aio", None)
    if aio is not None:
        _patch_google_models(getattr(aio, "models", None), is_async=True)
    return client


def _patch_google_models(models: Any, *, is_async: bool) -> None:
    if models is None:
        return
    if getattr(models, "_verdictlens_patched", False):
        return

    original_generate = getattr(models, "generate_content", None)
    if original_generate is None:
        return

    if is_async or _is_coroutine_func(original_generate):
        @functools.wraps(original_generate)
        async def patched_generate(*args: Any, **kwargs: Any) -> Any:
            if _active_span.get() is None:
                return await original_generate(*args, **kwargs)
            return await _trace_google_async(original_generate, args, kwargs)

        models.generate_content = patched_generate
    else:
        @functools.wraps(original_generate)
        def patched_generate(*args: Any, **kwargs: Any) -> Any:
            if _active_span.get() is None:
                return original_generate(*args, **kwargs)
            return _trace_google_sync(original_generate, args, kwargs)

        models.generate_content = patched_generate

    models._verdictlens_patched = True


def _trace_google_sync(
    fn: Callable[..., Any], args: tuple, kwargs: Dict[str, Any],
) -> Any:
    model = kwargs.get("model") or (args[0] if args else None) or "unknown"
    if not isinstance(model, str):
        model = str(model)
    input_snapshot = _snapshot_google_input(model, kwargs, args)

    t0 = time.perf_counter()
    error_dict: Optional[Dict[str, Any]] = None
    result: Any = None
    try:
        result = fn(*args, **kwargs)
        return result
    except BaseException as exc:
        error_dict = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _record_google_span(model, input_snapshot, result, error_dict, latency_ms)


async def _trace_google_async(
    fn: Callable[..., Any], args: tuple, kwargs: Dict[str, Any],
) -> Any:
    model = kwargs.get("model") or (args[0] if args else None) or "unknown"
    if not isinstance(model, str):
        model = str(model)
    input_snapshot = _snapshot_google_input(model, kwargs, args)

    t0 = time.perf_counter()
    error_dict: Optional[Dict[str, Any]] = None
    result: Any = None
    try:
        result = await fn(*args, **kwargs)
        return result
    except BaseException as exc:
        error_dict = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        _record_google_span(model, input_snapshot, result, error_dict, latency_ms)


def _snapshot_google_input(
    model: str, kwargs: Dict[str, Any], args: tuple,
) -> Dict[str, Any]:
    snap: Dict[str, Any] = {"model": model}
    contents = kwargs.get("contents") or (args[1] if len(args) > 1 else None)
    if contents is not None:
        snap["contents"] = safe_serialize(contents)
    config = kwargs.get("config")
    if config is not None:
        snap["config"] = safe_serialize(config)
    return snap


def _record_google_span(
    model: str,
    input_snapshot: Dict[str, Any],
    result: Any,
    error: Optional[Dict[str, Any]],
    latency_ms: float,
) -> None:
    output_data = None
    usage_dict: Optional[Dict[str, Optional[int]]] = None

    if result is not None and error is None:
        text = getattr(result, "text", None)
        output_data = {"role": "model", "content": text or safe_serialize(result)}

        usage = getattr(result, "usage_metadata", None)
        if usage is not None:
            prompt = getattr(usage, "prompt_token_count", None)
            completion = getattr(usage, "candidates_token_count", None)
            total = getattr(usage, "total_token_count", None)
            usage_dict = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total if total is not None else (
                    (prompt or 0) + (completion or 0)
                    if prompt is not None or completion is not None
                    else None
                ),
            }

    cost = estimate_cost_usd(model, usage_dict or {}) if usage_dict else None

    record_child_span(
        name=f"google.models.generate_content({model})",
        span_type="llm",
        model=model,
        input_data=input_snapshot,
        output_data=output_data,
        error=error,
        latency_ms=latency_ms,
        token_usage=usage_dict,
        cost_usd=cost,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_coroutine_func(fn: Any) -> bool:
    import asyncio
    import inspect
    return inspect.iscoroutinefunction(fn) or (
        hasattr(fn, "__wrapped__") and inspect.iscoroutinefunction(fn.__wrapped__)
    )
