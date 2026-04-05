"""
Pytest fixtures for the VerdictLens backend test suite.

These tests exercise the API layer **without** requiring a running ClickHouse
or Redis instance by monkey-patching the persistence and broadcast layers.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models import MetricsResponse, TraceDetailOut, TraceIn, TraceListResponse, TraceOut


# ---------------------------------------------------------------------------
# In-memory trace store (replaces ClickHouse)
# ---------------------------------------------------------------------------

class FakeStore:
    """
    In-memory trace store that mimics the ClickHouse helpers.
    """

    def __init__(self) -> None:
        """Initialize empty stores."""
        self.traces: Dict[str, Dict[str, Any]] = {}
        self.spans: List[Dict[str, Any]] = []

    def insert_trace(self, trace: TraceIn, settings: Any = None) -> None:
        """
        Persist a trace and its spans in memory.

        :param trace: Incoming trace payload.
        :param settings: Ignored.
        :returns: None
        """
        tu = trace.token_usage
        self.traces[trace.trace_id] = {
            "trace_id": trace.trace_id,
            "name": trace.name,
            "start_time": trace.start_time,
            "end_time": trace.end_time,
            "latency_ms": trace.latency_ms,
            "status": trace.status,
            "framework": trace.framework,
            "model": trace.model,
            "input": trace.input,
            "output": trace.output,
            "prompt_tokens": tu.prompt_tokens if tu else None,
            "completion_tokens": tu.completion_tokens if tu else None,
            "total_tokens": tu.total_tokens if tu else None,
            "cost_usd": trace.cost_usd,
            "error": trace.error,
            "span_count": len(trace.spans),
            "metadata": trace.metadata,
        }
        for sp in trace.spans:
            stu = sp.token_usage
            self.spans.append({
                "span_id": sp.span_id,
                "parent_span_id": sp.parent_span_id,
                "trace_id": trace.trace_id,
                "name": sp.name,
                "span_type": sp.span_type,
                "start_time": sp.start_time,
                "end_time": sp.end_time,
                "latency_ms": sp.latency_ms,
                "model": sp.model,
                "input": sp.input,
                "output": sp.output,
                "prompt_tokens": stu.prompt_tokens if stu else None,
                "completion_tokens": stu.completion_tokens if stu else None,
                "total_tokens": stu.total_tokens if stu else None,
                "cost_usd": sp.cost_usd,
                "error": sp.error,
                "metadata": sp.metadata,
            })

    def list_traces(self, **kwargs: Any) -> TraceListResponse:
        """
        Return all traces as a single page.

        :param kwargs: Ignored filter params.
        :returns: Trace list response.
        """
        items = list(self.traces.values())
        items.sort(key=lambda t: t.get("start_time") or "", reverse=True)
        page = kwargs.get("page", 1)
        page_size = kwargs.get("page_size", 50)
        out: List[TraceOut] = []
        for t in items:
            out.append(TraceOut(
                trace_id=t["trace_id"],
                name=t["name"],
                start_time=t.get("start_time"),
                end_time=t.get("end_time"),
                latency_ms=t.get("latency_ms"),
                status=t.get("status", "ok"),
                framework=t.get("framework"),
                model=t.get("model"),
                cost_usd=t.get("cost_usd"),
                error=t.get("error"),
                span_count=t.get("span_count", 0),
                prompt_tokens=t.get("prompt_tokens"),
                completion_tokens=t.get("completion_tokens"),
                total_tokens=t.get("total_tokens"),
                metadata=t.get("metadata", {}),
            ))
        return TraceListResponse(traces=out, total=len(out), page=page, page_size=page_size)

    def get_trace(self, trace_id: str, settings: Any = None, **kwargs: Any) -> Optional[TraceDetailOut]:
        """
        Fetch a trace and its spans by id.

        :param trace_id: Trace id.
        :param settings: Ignored.
        :returns: Detail or None.
        """
        t = self.traces.get(trace_id)
        if not t:
            return None
        from app.models import SpanOut, TokenUsageOut

        tu = None
        if any(t.get(k) is not None for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
            tu = TokenUsageOut(
                prompt_tokens=t.get("prompt_tokens"),
                completion_tokens=t.get("completion_tokens"),
                total_tokens=t.get("total_tokens"),
            )
        spans_out: List[Any] = []
        for sp in self.spans:
            if sp["trace_id"] != trace_id:
                continue
            stu = None
            if any(sp.get(k) is not None for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
                stu = TokenUsageOut(
                    prompt_tokens=sp.get("prompt_tokens"),
                    completion_tokens=sp.get("completion_tokens"),
                    total_tokens=sp.get("total_tokens"),
                )
            spans_out.append(SpanOut(
                span_id=sp["span_id"],
                parent_span_id=sp.get("parent_span_id"),
                trace_id=sp["trace_id"],
                name=sp["name"],
                span_type=sp["span_type"],
                start_time=sp.get("start_time"),
                end_time=sp.get("end_time"),
                latency_ms=sp.get("latency_ms"),
                model=sp.get("model"),
                input=sp.get("input"),
                output=sp.get("output"),
                token_usage=stu,
                cost_usd=sp.get("cost_usd"),
                error=sp.get("error"),
                metadata=sp.get("metadata", {}),
            ))
        return TraceDetailOut(
            trace_id=t["trace_id"],
            name=t["name"],
            start_time=t.get("start_time"),
            end_time=t.get("end_time"),
            latency_ms=t.get("latency_ms"),
            status=t.get("status", "ok"),
            framework=t.get("framework"),
            model=t.get("model"),
            input=t.get("input"),
            output=t.get("output"),
            token_usage=tu,
            cost_usd=t.get("cost_usd"),
            error=t.get("error"),
            spans=spans_out,
            metadata=t.get("metadata", {}),
        )

    def get_metrics(self, **kwargs: Any) -> MetricsResponse:
        """
        Compute basic metrics from the in-memory store.

        :param kwargs: Ignored.
        :returns: Metrics response.
        """
        total = len(self.traces)
        errors = sum(1 for t in self.traces.values() if t.get("status") == "error")
        return MetricsResponse(
            total_traces=total,
            total_spans=len(self.spans),
            total_cost_usd=sum(t.get("cost_usd") or 0 for t in self.traces.values()),
            total_tokens=sum(t.get("total_tokens") or 0 for t in self.traces.values()),
            avg_latency_ms=None,
            error_rate=round(errors / total, 4) if total else 0.0,
        )


_store = FakeStore()


@pytest.fixture(autouse=True)
def _patch_clickhouse(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Replace ClickHouse functions with the in-memory fake store.

    :param monkeypatch: pytest monkeypatch.
    :returns: None
    """
    _store.traces.clear()
    _store.spans.clear()

    import app.routes as routes_mod
    import app.clickhouse as ch_mod

    monkeypatch.setattr(routes_mod, "insert_trace", _store.insert_trace)
    monkeypatch.setattr(routes_mod, "list_traces", _store.list_traces)
    monkeypatch.setattr(routes_mod, "get_trace", _store.get_trace)
    monkeypatch.setattr(routes_mod, "get_metrics", _store.get_metrics)

    monkeypatch.setattr(ch_mod, "ensure_schema", lambda *a, **kw: None)
    monkeypatch.setattr(ch_mod, "close_client", lambda: None)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """
    Async HTTP test client for the FastAPI app (no live server needed).

    :yields: httpx AsyncClient.
    """
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
