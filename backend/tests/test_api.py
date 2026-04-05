"""
Integration tests for the VerdictLens API endpoints.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_trace(**overrides: Any) -> Dict[str, Any]:
    """
    Build a minimal valid trace payload.

    :param overrides: Fields to override on the default.
    :returns: JSON-serializable trace dict.
    """
    base: Dict[str, Any] = {
        "trace_id": "t-001",
        "name": "test_agent",
        "start_time": "2026-03-24T12:00:00Z",
        "end_time": "2026-03-24T12:00:01Z",
        "latency_ms": 1000.0,
        "status": "ok",
        "framework": "openai",
        "model": "gpt-4o-mini",
        "input": {"query": "hello"},
        "output": {"answer": "world"},
        "token_usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
        "cost_usd": 0.001,
        "error": None,
        "spans": [
            {
                "span_id": "s-001",
                "name": "llm_call",
                "span_type": "llm",
                "start_time": "2026-03-24T12:00:00Z",
                "end_time": "2026-03-24T12:00:00.800Z",
                "latency_ms": 800.0,
                "model": "gpt-4o-mini",
                "input": {"messages": [{"role": "user", "content": "hello"}]},
                "output": {"content": "world"},
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
                "cost_usd": 0.001,
            }
        ],
        "metadata": {"sdk": "verdictlens"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    """
    /health should return 200 ok.

    :param client: Test client.
    :returns: None
    """
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /traces
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_trace(client: AsyncClient) -> None:
    """
    POST /traces should accept a valid trace and return 201.

    :param client: Test client.
    :returns: None
    """
    resp = await client.post("/traces", json=_sample_trace())
    assert resp.status_code == 201
    body = resp.json()
    assert body["trace_id"] == "t-001"
    assert body["status"] == "accepted"


@pytest.mark.asyncio
async def test_ingest_minimal_trace(client: AsyncClient) -> None:
    """
    POST /traces with only required fields should succeed.

    :param client: Test client.
    :returns: None
    """
    resp = await client.post("/traces", json={"name": "bare_agent"})
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_ingest_error_trace(client: AsyncClient) -> None:
    """
    POST /traces with status=error should persist correctly.

    :param client: Test client.
    :returns: None
    """
    resp = await client.post(
        "/traces",
        json=_sample_trace(trace_id="t-err", status="error", error="RuntimeError: boom"),
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /traces
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_traces_empty(client: AsyncClient) -> None:
    """
    GET /traces on empty store returns an empty list with total=0.

    :param client: Test client.
    :returns: None
    """
    resp = await client.get("/traces")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["traces"] == []


@pytest.mark.asyncio
async def test_list_traces_after_ingest(client: AsyncClient) -> None:
    """
    GET /traces after inserting one trace should return it.

    :param client: Test client.
    :returns: None
    """
    await client.post("/traces", json=_sample_trace())
    resp = await client.get("/traces")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["traces"][0]["trace_id"] == "t-001"


# ---------------------------------------------------------------------------
# GET /traces/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_trace_detail(client: AsyncClient) -> None:
    """
    GET /traces/t-001 after ingest should return full detail with spans.

    :param client: Test client.
    :returns: None
    """
    await client.post("/traces", json=_sample_trace())
    resp = await client.get("/traces/t-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_id"] == "t-001"
    assert len(body["spans"]) == 1
    assert body["spans"][0]["span_id"] == "s-001"


@pytest.mark.asyncio
async def test_get_trace_not_found(client: AsyncClient) -> None:
    """
    GET /traces/nonexistent should return 404.

    :param client: Test client.
    :returns: None
    """
    resp = await client.get("/traces/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_empty(client: AsyncClient) -> None:
    """
    GET /metrics with no traces should return zeros.

    :param client: Test client.
    :returns: None
    """
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_traces"] == 0
    assert body["error_rate"] == 0.0


@pytest.mark.asyncio
async def test_metrics_after_ingest(client: AsyncClient) -> None:
    """
    GET /metrics after ingesting traces should reflect counts and costs.

    :param client: Test client.
    :returns: None
    """
    await client.post("/traces", json=_sample_trace())
    await client.post(
        "/traces",
        json=_sample_trace(trace_id="t-002", status="error", error="ValueError: bad"),
    )
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_traces"] == 2
    assert body["total_spans"] == 2
    assert body["error_rate"] == 0.5


# ---------------------------------------------------------------------------
# Schema / model validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_invalid_status_normalized(client: AsyncClient) -> None:
    """
    POST /traces with unknown status should be accepted (normalized to 'success').

    :param client: Test client.
    :returns: None
    """
    resp = await client.post("/traces", json=_sample_trace(status="unknown"))
    assert resp.status_code == 201
