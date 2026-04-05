"""
Optional OpenTelemetry exporter — emits standard OTel spans in parallel
with the native VerdictLens transport.

Install: ``pip install verdictlens[otel]``

When ``configure(otel_export=True)`` is set, every trace sent by the SDK
is *also* translated into an OTel span and exported to the configured
OTLP endpoint.  This gives Java / Go / Ruby / Node.js compatibility for free
via any OTel collector.

This module is a no-op if ``opentelemetry-sdk`` is not installed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("verdictlens.otel")

_tracer: Optional[Any] = None
_initialized = False


def init_otel(
    *,
    service_name: str = "verdictlens",
    otel_endpoint: str = "http://localhost:4317",
) -> bool:
    """
    Initialize the OTel TracerProvider and OTLP exporter.

    Safe to call multiple times — only the first call takes effect.

    :param service_name: OTel service name resource attribute.
    :param otel_endpoint: OTLP gRPC endpoint (e.g. ``http://otel-collector:4317``).
    :returns: True if initialization succeeded, False if OTel is unavailable.
    """
    global _tracer, _initialized
    if _initialized:
        return _tracer is not None

    _initialized = True
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.info(
            "verdictlens: opentelemetry-sdk not installed — OTel export disabled. "
            "Install with: pip install verdictlens[otel]"
        )
        return False

    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)
        _tracer = otel_trace.get_tracer("verdictlens", "0.2.0")
        logger.info("verdictlens: OTel export enabled → %s", otel_endpoint)
        return True
    except Exception as exc:
        logger.warning("verdictlens: OTel initialization failed: %s", exc)
        return False


def export_trace_as_otel(payload: Dict[str, Any]) -> None:
    """
    Translate an VerdictLens trace payload into OTel spans and export them.

    Maps VerdictLens fields to OTel span attributes:

    - ``trace_id`` → span name prefix
    - ``name`` → span name
    - ``framework`` → ``verdictlens.framework``
    - ``model`` → ``verdictlens.model``
    - ``latency_ms`` → ``verdictlens.latency_ms``
    - ``status`` → OTel span status
    - ``error`` → OTel exception event
    - Token counts → ``verdictlens.tokens.*``
    - ``cost_usd`` → ``verdictlens.cost_usd``
    - ``decision`` → ``verdictlens.decision``
    - ``confidence_score`` → ``verdictlens.confidence_score``

    :param payload: JSON-serializable trace dict (same shape as POST /traces body).
    :returns: None (best-effort, never raises).
    """
    if _tracer is None:
        return

    try:
        _do_export(payload)
    except Exception as exc:
        logger.debug("verdictlens: OTel export error: %s", exc)


def _do_export(payload: Dict[str, Any]) -> None:
    """
    Internal export logic — creates OTel spans from the trace payload.

    :param payload: Trace dict.
    :returns: None
    """
    from opentelemetry import trace as otel_trace
    from opentelemetry.trace import StatusCode

    trace_name = payload.get("name", "agent_run")
    spans_data = payload.get("spans", [])

    with _tracer.start_as_current_span(trace_name) as root_span:
        _set_span_attributes(root_span, payload)

        status = payload.get("status", "success")
        if status == "error":
            root_span.set_status(StatusCode.ERROR, payload.get("error", {}).get("message", ""))
            err = payload.get("error")
            if isinstance(err, dict):
                root_span.add_event("exception", {
                    "exception.type": err.get("type", "Error"),
                    "exception.message": err.get("message", ""),
                    "exception.stacktrace": err.get("stack", ""),
                })

        for span_data in spans_data:
            with _tracer.start_span(span_data.get("name", "span")) as child:
                _set_span_attributes(child, span_data)
                sp_err = span_data.get("error")
                if sp_err:
                    child.set_status(StatusCode.ERROR)
                    if isinstance(sp_err, dict):
                        child.add_event("exception", {
                            "exception.type": sp_err.get("type", "Error"),
                            "exception.message": sp_err.get("message", ""),
                            "exception.stacktrace": sp_err.get("stack", ""),
                        })


def _set_span_attributes(span: Any, data: Dict[str, Any]) -> None:
    """
    Map VerdictLens fields to OTel span attributes.

    :param span: OTel span object.
    :param data: Trace or span dict.
    :returns: None
    """
    _safe_set(span, "verdictlens.trace_id", data.get("trace_id"))
    _safe_set(span, "verdictlens.framework", data.get("framework"))
    _safe_set(span, "verdictlens.model", data.get("model"))
    _safe_set(span, "verdictlens.span_type", data.get("span_type"))
    _safe_set(span, "verdictlens.decision", data.get("decision"))

    latency = data.get("latency_ms")
    if latency is not None:
        span.set_attribute("verdictlens.latency_ms", float(latency))

    confidence = data.get("confidence_score")
    if confidence is not None:
        span.set_attribute("verdictlens.confidence_score", float(confidence))

    cost = data.get("cost_usd")
    if cost is not None:
        span.set_attribute("verdictlens.cost_usd", float(cost))

    tu = data.get("token_usage") or {}
    if isinstance(tu, dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            val = tu.get(key)
            if val is not None:
                span.set_attribute(f"verdictlens.tokens.{key}", int(val))


def _safe_set(span: Any, key: str, value: Any) -> None:
    """
    Set an OTel attribute only if the value is non-null.

    :param span: OTel span.
    :param key: Attribute key.
    :param value: Attribute value.
    :returns: None
    """
    if value is not None:
        span.set_attribute(key, str(value))


def shutdown_otel() -> None:
    """
    Flush and shut down the OTel TracerProvider.

    :returns: None
    """
    try:
        from opentelemetry import trace as otel_trace

        provider = otel_trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        pass
