"""
LangChain core callback handler (``langchain-core``).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from verdictlens.pricing import estimate_cost_usd
from verdictlens.serializers import safe_serialize
from verdictlens.trace import emit_trace
from verdictlens.types import SpanRecord, TokenUsage, TraceEvent, utc_now_iso

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.outputs import LLMResult
except ImportError:  # pragma: no cover - optional dependency
    BaseCallbackHandler = object  # type: ignore[misc,assignment]
    LLMResult = Any  # type: ignore[misc,assignment]


def _now_ms() -> float:
    """
    Monotonic milliseconds.

    :returns: Elapsed ms from perf counter epoch (scaled).
    """
    return time.perf_counter() * 1000.0


class VerdictLensLangChainCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that aggregates chain runs into VerdictLens traces.

    :param trace_name_prefix: Optional prefix for emitted trace names.
    """

    def __init__(self, trace_name_prefix: str = "langchain") -> None:
        """
        Initialize handler state.

        :param trace_name_prefix: Prefix used when naming traces.
        """
        if BaseCallbackHandler is object:
            raise ImportError("verdictlens LangChain integration requires `pip install langchain-core`")
        super().__init__()
        self._trace_name_prefix = trace_name_prefix
        self._runs: Dict[UUID, Dict[str, Any]] = {}

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize trace state for a chain run.

        :param serialized: Serialized chain descriptor.
        :param inputs: Chain inputs.
        :param run_id: LangChain run identifier.
        :param parent_run_id: Parent run id when nested.
        :param tags: Optional tags.
        :param metadata: Optional metadata.
        :param kwargs: Extra callback kwargs.
        :returns: None
        """
        _ = parent_run_id, tags, metadata, kwargs
        name = self._trace_name_prefix
        try:
            name = f"{self._trace_name_prefix}:{serialized.get('name', 'chain')}"
        except Exception:
            pass
        self._runs[run_id] = {
            "name": name,
            "start_wall": utc_now_iso(),
            "t0": _now_ms(),
            "inputs": safe_serialize(inputs),
            "spans": [],
            "error": None,
        }

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """
        Record an LLM span against the parent chain run (if known).

        :param response: LLM result object.
        :param run_id: LLM run id.
        :param parent_run_id: Parent chain run id.
        :param kwargs: Extra callback kwargs.
        :returns: None
        """
        _ = run_id, kwargs
        target_run = parent_run_id
        if target_run is None or target_run not in self._runs:
            target_run = self._pick_latest_run()
        if target_run is None:
            self._emit_llm_only_trace(response)
            return

        llm_output = getattr(response, "llm_output", None) or {}
        model = None
        if isinstance(llm_output, dict):
            model = llm_output.get("model_name")
        usage = None
        token_usage = None
        try:
            if response.llm_output and isinstance(response.llm_output, dict):
                usage = response.llm_output.get("token_usage")
        except Exception:
            usage = None
        usage_dict: Optional[Dict[str, Optional[int]]] = None
        if isinstance(usage, dict):
            usage_dict = {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
            token_usage = TokenUsage(
                prompt_tokens=usage_dict.get("prompt_tokens"),
                completion_tokens=usage_dict.get("completion_tokens"),
                total_tokens=usage_dict.get("total_tokens"),
            )
        model_str = str(model) if model is not None else None
        cost = estimate_cost_usd(model_str, usage_dict or {}) if usage_dict else None

        start_wall = utc_now_iso()
        span = SpanRecord(
            name="llm",
            span_type="llm",
            start_time=start_wall,
            end_time=utc_now_iso(),
            latency_ms=None,
            model=model_str,
            input=None,
            output=safe_serialize(getattr(response, "generations", None)),
            token_usage=token_usage,
            cost_usd=cost,
            metadata={"integration": "langchain", "llm_run_id": str(run_id)},
        )
        self._runs[target_run]["spans"].append(span)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """
        Record a chain-level error string.

        :param error: Exception raised by the chain.
        :param run_id: Chain run id.
        :param kwargs: Extra callback kwargs.
        :returns: None
        """
        _ = kwargs
        state = self._runs.get(run_id)
        if not state:
            return
        state["error"] = f"{type(error).__name__}: {error}"

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """
        Finalize and emit the trace for a completed chain run.

        :param outputs: Chain outputs.
        :param run_id: Chain run id.
        :param kwargs: Extra callback kwargs.
        :returns: None
        """
        _ = kwargs
        state = self._runs.pop(run_id, None)
        if not state:
            return
        end_wall = utc_now_iso()
        latency = round(_now_ms() - float(state["t0"]), 3)
        err = state.get("error")
        spans: List[SpanRecord] = list(state.get("spans", []))
        root = SpanRecord(
            name=str(state["name"]),
            span_type="chain",
            start_time=str(state["start_wall"]),
            end_time=end_wall,
            latency_ms=latency,
            input=state.get("inputs"),
            output=safe_serialize(outputs) if err is None else None,
            error=str(err) if err else None,
            metadata={"integration": "langchain", "run_id": str(run_id)},
        )
        spans.insert(0, root)

        event = TraceEvent(
            name=str(state["name"]),
            start_time=str(state["start_wall"]),
            end_time=end_wall,
            latency_ms=latency,
            status="error" if err else "ok",
            framework="langchain",
            model=None,
            input=root.input,
            output=root.output,
            error=str(err) if err else None,
            spans=spans,
        )
        emit_trace(event)

    def _pick_latest_run(self) -> Optional[UUID]:
        """
        Best-effort parent run selection when LangChain omits ``parent_run_id``.

        :returns: A run uuid or None.
        """
        if not self._runs:
            return None
        try:
            return next(iter(self._runs.keys()))
        except StopIteration:
            return None

    def _emit_llm_only_trace(self, response: LLMResult) -> None:
        """
        Emit a standalone trace when an LLM call has no known parent chain.

        :param response: LLM result object.
        :returns: None
        """
        start_wall = utc_now_iso()
        end_wall = utc_now_iso()
        span = SpanRecord(
            name=f"{self._trace_name_prefix}:llm",
            span_type="llm",
            start_time=start_wall,
            end_time=end_wall,
            latency_ms=None,
            model=None,
            output=safe_serialize(getattr(response, "generations", None)),
            metadata={"integration": "langchain", "orphan_llm": True},
        )
        emit_trace(
            TraceEvent(
                name=span.name,
                start_time=start_wall,
                end_time=end_wall,
                status="ok",
                framework="langchain",
                spans=[span],
            )
        )


__all__ = ["VerdictLensLangChainCallbackHandler"]
