"""
LlamaIndex (``llama-index-core``) callback handler.
"""

from __future__ import annotations

import time
from typing import Any, List, Optional
from uuid import uuid4

from verdictlens.serializers import safe_serialize
from verdictlens.trace import emit_trace
from verdictlens.types import SpanRecord, TraceEvent, utc_now_iso

try:
    from llama_index.core.callbacks.base_handler import BaseCallbackHandler
    from llama_index.core.callbacks.schema import CBEventType
except ImportError:  # pragma: no cover - optional dependency
    BaseCallbackHandler = object  # type: ignore[misc,assignment]
    CBEventType = Any  # type: ignore[misc,assignment]


def _now_ms() -> float:
    """
    Monotonic milliseconds.

    :returns: Scaled perf counter time.
    """
    return time.perf_counter() * 1000.0


class VerdictLensLlamaIndexCallbackHandler(BaseCallbackHandler):
    """
    LlamaIndex callback handler emitting VerdictLens traces for LLM events.

    :param trace_prefix: Name prefix for traces.
    """

    def __init__(self, trace_prefix: str = "llamaindex") -> None:
        """
        Initialize handler state.

        :param trace_prefix: Prefix for emitted trace names.
        """
        if BaseCallbackHandler is object:
            raise ImportError(
                "verdictlens LlamaIndex integration requires `pip install llama-index-core`"
            )
        super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        self._trace_prefix = trace_prefix
        self._starts: dict[str, float] = {}

    def on_event_start(
        self,
        event_type: CBEventType,
        payload: Optional[dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> str:
        """
        Record start timestamps for relevant event types.

        :param event_type: LlamaIndex event type.
        :param payload: Event payload.
        :param event_id: Event identifier.
        :param kwargs: Additional kwargs.
        :returns: Event id for correlation.
        """
        _ = kwargs
        if event_id == "":
            event_id = str(uuid4())
        try:
            if event_type == CBEventType.LLM:
                self._starts[event_id] = _now_ms()
        except Exception:
            pass
        return event_id

    def on_event_end(
        self,
        event_type: CBEventType,
        payload: Optional[dict[str, Any]] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        """
        Emit a trace when an LLM event completes.

        :param event_type: LlamaIndex event type.
        :param payload: Event payload.
        :param event_id: Event identifier.
        :param kwargs: Additional kwargs.
        :returns: None
        """
        _ = kwargs
        try:
            if event_type != CBEventType.LLM:
                return
        except Exception:
            return

        start = self._starts.pop(event_id, None)
        end_wall = utc_now_iso()
        latency = None if start is None else round(_now_ms() - float(start), 3)

        span = SpanRecord(
            name=f"{self._trace_prefix}:llm",
            span_type="llm",
            start_time=end_wall,
            end_time=end_wall,
            latency_ms=latency,
            input=safe_serialize(payload),
            metadata={"integration": "llamaindex", "event_id": event_id},
        )
        emit_trace(
            TraceEvent(
                name=span.name,
                start_time=end_wall,
                end_time=end_wall,
                latency_ms=latency,
                status="ok",
                framework="llamaindex",
                spans=[span],
            )
        )

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        """
        Satisfy LlamaIndex callback interface.

        :param trace_id: Trace id.
        :returns: None
        """
        _ = trace_id

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[dict[str, List[str]]] = None,
    ) -> None:
        """
        Satisfy LlamaIndex callback interface.

        :param trace_id: Trace id.
        :param trace_map: Trace map.
        :returns: None
        """
        _ = trace_id, trace_map


__all__ = ["VerdictLensLlamaIndexCallbackHandler"]
