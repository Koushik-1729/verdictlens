"""
Canonical schema contract for VerdictLens traces and spans.

This module is the **single source of truth** for field names, types, defaults,
and constraints used across the Python SDK, FastAPI backend, and ClickHouse
storage layer.  Any change here must be reflected in:

- ``sdk/verdictlens/types.py``      (Pydantic models emitted by the SDK)
- ``backend/app/models.py``        (Pydantic request / response models)
- ``backend/app/clickhouse.py``    (DDL and insert / query logic)
- ``frontend/src/lib/api.ts``      (TypeScript interfaces)

SCHEMA_VERSION is bumped on every breaking field change.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

# ── Version ─────────────────────────────────────────────────────
SCHEMA_VERSION = "2.0.0"

# ── Status values ───────────────────────────────────────────────
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_RUNNING = "running"
STATUS_OK = "ok"  # legacy alias for STATUS_SUCCESS

VALID_STATUSES = frozenset({STATUS_SUCCESS, STATUS_ERROR, STATUS_RUNNING, STATUS_OK})


def normalize_status(raw: str) -> str:
    """
    Map legacy ``"ok"`` to ``"success"``; pass through valid values unchanged.

    :param raw: Raw status string.
    :returns: Normalized status.
    """
    if raw == STATUS_OK:
        return STATUS_SUCCESS
    return raw if raw in VALID_STATUSES else STATUS_SUCCESS


# ── Span types ──────────────────────────────────────────────────
SPAN_TYPE_AGENT = "agent"
SPAN_TYPE_LLM = "llm"
SPAN_TYPE_TOOL = "tool"
SPAN_TYPE_CHAIN = "chain"
SPAN_TYPE_RETRIEVAL = "retrieval"
SPAN_TYPE_OTHER = "other"

VALID_SPAN_TYPES = frozenset({
    SPAN_TYPE_AGENT,
    SPAN_TYPE_LLM,
    SPAN_TYPE_TOOL,
    SPAN_TYPE_CHAIN,
    SPAN_TYPE_RETRIEVAL,
    SPAN_TYPE_OTHER,
})


# ── Structured error ───────────────────────────────────────────
class ErrorDetail(BaseModel):
    """
    Structured error envelope attached to a span or trace.

    :param type: Exception class name (e.g. ``"ValueError"``).
    :param message: Human-readable error message.
    :param stack: Full stack trace string, or ``None`` if unavailable.
    """

    type: str = "Error"
    message: str = ""
    stack: Optional[str] = None


def normalize_error(raw: object) -> Optional[dict]:
    """
    Accept a plain string, dict, or ``None`` and return a canonical error dict.

    :param raw: Raw error value from any source.
    :returns: ``{"type": ..., "message": ..., "stack": ...}`` or ``None``.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        if not raw:
            return None
        parts = raw.split(": ", 1)
        etype = parts[0] if len(parts) == 2 else "Error"
        emsg = parts[1] if len(parts) == 2 else raw
        return {"type": etype, "message": emsg, "stack": None}
    if isinstance(raw, dict):
        return {
            "type": raw.get("type", "Error"),
            "message": raw.get("message", str(raw)),
            "stack": raw.get("stack"),
        }
    return {"type": "Error", "message": str(raw), "stack": None}


# ── Blame engine weights (configurable defaults) ───────────────
BLAME_WEIGHT_INPUT_ANOMALY = 0.35
BLAME_WEIGHT_OUTPUT_DEVIATION = 0.25
BLAME_WEIGHT_LOW_CONFIDENCE = 0.20
BLAME_WEIGHT_ERROR_PROPAGATION = 0.20

DEFAULT_CONFIDENCE = 0.5  # used when confidence_score is unset
