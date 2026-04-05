"""
Pydantic models for trace payloads sent to the VerdictLens backend.

Derives field names, types, and constraints from :mod:`verdictlens.schema`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from verdictlens.schema import normalize_error, normalize_status


def utc_now_iso() -> str:
    """
    Current UTC timestamp in ISO-8601 format with Z suffix.

    :returns: ISO timestamp string.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TokenUsage(BaseModel):
    """
    Token accounting for a model call.

    :param prompt_tokens: Tokens in the prompt/context.
    :param completion_tokens: Tokens in the model output.
    :param total_tokens: Total tokens if provided by the provider.
    """

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class SpanRecord(BaseModel):
    """
    A single span within a trace (e.g., LLM call, tool, retrieval).

    :param span_id: Stable identifier for this span.
    :param parent_span_id: Parent span id for tree reconstruction / blame.
    :param name: Human-readable span name.
    :param span_type: Span classification.
    :param start_time: ISO start timestamp.
    :param end_time: ISO end timestamp.
    :param latency_ms: Wall-clock latency in milliseconds.
    :param model: Model name when applicable.
    :param input: Structured/redacted input payload.
    :param output: Structured/redacted output payload.
    :param decision: Why the agent took this action (human-readable).
    :param confidence_score: Agent confidence in [0.0, 1.0].
    :param token_usage: Token usage when applicable.
    :param cost_usd: Estimated or provider-reported cost in USD.
    :param error: Structured error dict ``{type, message, stack}`` or legacy string.
    :param metadata: Arbitrary structured metadata.
    """

    span_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_span_id: Optional[str] = None
    name: str = "span"
    span_type: Literal["agent", "llm", "tool", "chain", "retrieval", "other"] = "other"
    start_time: str = Field(default_factory=utc_now_iso)
    end_time: Optional[str] = None
    latency_ms: Optional[float] = None
    model: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    decision: Optional[str] = None
    confidence_score: Optional[float] = None
    token_usage: Optional[TokenUsage] = None
    cost_usd: Optional[float] = None
    error: Optional[Any] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_span_ids: List[str] = Field(default_factory=list)

    @field_validator("error", mode="before")
    @classmethod
    def _normalize_error(cls, v: Any) -> Any:
        """Normalize string errors to ``{type, message, stack}`` dicts."""
        return normalize_error(v)

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> Any:
        """Clamp confidence_score to [0.0, 1.0]."""
        if v is None:
            return None
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return None

    @field_validator("metadata", mode="before")
    @classmethod
    def _default_metadata(cls, value: Any) -> Dict[str, Any]:
        """Ensure metadata is always a dict."""
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        return {"value": value}


class TraceEvent(BaseModel):
    """
    Top-level trace envelope ingested by the backend.

    :param trace_id: Unique trace identifier.
    :param name: Trace/agent run name.
    :param start_time: Trace start time (ISO).
    :param end_time: Trace end time (ISO).
    :param latency_ms: Total latency in milliseconds.
    :param status: success, error, or running.
    :param framework: Detected or declared framework integration.
    :param model: Primary model identifier when known.
    :param input: Root input payload.
    :param output: Root output payload.
    :param decision: Root-level decision rationale.
    :param confidence_score: Root-level confidence [0.0, 1.0].
    :param token_usage: Aggregated token usage for the trace root span.
    :param cost_usd: Total estimated cost in USD.
    :param error: Structured error dict or None.
    :param spans: Child spans (decision tree / steps).
    :param metadata: Additional metadata (SDK version, host, etc.).
    """

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = "agent_run"
    start_time: str = Field(default_factory=utc_now_iso)
    end_time: Optional[str] = None
    latency_ms: Optional[float] = None
    status: Literal["ok", "success", "error", "running"] = "success"
    framework: Optional[str] = None
    model: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    decision: Optional[str] = None
    confidence_score: Optional[float] = None
    token_usage: Optional[TokenUsage] = None
    cost_usd: Optional[float] = None
    error: Optional[Any] = None
    spans: List[SpanRecord] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> str:
        """Map legacy ``'ok'`` to ``'success'``."""
        if isinstance(v, str):
            return normalize_status(v)
        return "success"

    @field_validator("error", mode="before")
    @classmethod
    def _normalize_error(cls, v: Any) -> Any:
        """Normalize string errors to ``{type, message, stack}`` dicts."""
        return normalize_error(v)

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> Any:
        """Clamp confidence_score to [0.0, 1.0]."""
        if v is None:
            return None
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return None

    @field_validator("metadata", mode="before")
    @classmethod
    def _default_metadata(cls, value: Any) -> Dict[str, Any]:
        """Ensure metadata is always a dict."""
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        return {"value": value}
