"""
Tests for the ``@trace`` decorator and trace emission.
"""

from __future__ import annotations

import asyncio
import queue
import shutil
from pathlib import Path
from typing import Any, Dict, List

import pytest

from verdictlens import configure, trace
from verdictlens.client import VerdictLensClient, get_client, set_client


def test_trace_sync_success(captured_traces: List[Dict[str, Any]]) -> None:
    """
    A successful sync call should emit a trace payload.

    :param captured_traces: Captured trace dicts from the transport monkeypatch.
    :returns: None
    """
    configure(base_url="http://test", disabled=False, reset_client=True)

    @trace(name="demo")
    def add(a: int, b: int) -> int:
        """
        Add two integers.

        :param a: Left operand.
        :param b: Right operand.
        :returns: Sum.
        """
        return a + b

    assert add(2, 3) == 5
    get_client().flush(timeout=3.0)

    assert len(captured_traces) == 1
    assert captured_traces[0]["name"] == "demo"
    assert captured_traces[0]["status"] in ("ok", "success")


def test_trace_sync_error_posts_error_status(captured_traces: List[Dict[str, Any]]) -> None:
    """
    Exceptions should be recorded as trace errors without swallowing the exception.

    :param captured_traces: Captured trace dicts from the transport monkeypatch.
    :returns: None
    """
    configure(base_url="http://test", disabled=False, reset_client=True)

    @trace(name="boom")
    def boom() -> None:
        """
        Always raise.

        :returns: Never.
        """
        raise ValueError("nope")

    with pytest.raises(ValueError):
        boom()

    get_client().flush(timeout=3.0)
    assert len(captured_traces) == 1
    assert captured_traces[0]["status"] == "error"
    assert "ValueError" in str(captured_traces[0].get("error", ""))


@pytest.mark.asyncio
async def test_trace_async_success(captured_traces: List[Dict[str, Any]]) -> None:
    """
    Async functions should be traced similarly to sync functions.

    :param captured_traces: Captured trace dicts from the transport monkeypatch.
    :returns: None
    """
    configure(base_url="http://test", disabled=False, reset_client=True)

    @trace(name="async_demo")
    async def work(x: int) -> int:
        """
        Async identity with a tiny delay.

        :param x: Input.
        :returns: Input.
        """
        await asyncio.sleep(0.01)
        return x

    assert await work(7) == 7
    get_client().flush(timeout=3.0)
    assert len(captured_traces) == 1


def test_trace_disabled_does_not_post(captured_traces: List[Dict[str, Any]]) -> None:
    """
    Disabled SDK should not emit trace payloads.

    :param captured_traces: Captured trace dicts from the transport monkeypatch.
    :returns: None
    """
    configure(base_url="http://test", disabled=True, reset_client=True)

    @trace
    def quiet() -> int:
        """
        Return a constant.

        :returns: Constant int.
        """
        return 1

    assert quiet() == 1
    get_client().flush(timeout=1.0)
    assert captured_traces == []


def test_trace_extracts_usage_from_dict_return_value(
    captured_traces: List[Dict[str, Any]],
) -> None:
    """
    Return values that include OpenAI-like usage should populate token fields.

    :param captured_traces: Captured trace dicts from the transport monkeypatch.
    :returns: None
    """
    configure(base_url="http://test", disabled=False, reset_client=True)

    @trace(name="llmish")
    def fake_llm() -> Dict[str, Any]:
        """
        Return a dict resembling an OpenAI response.

        :returns: Dict with usage + model.
        """
        return {
            "model": "gpt-4o-mini",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

    fake_llm()
    get_client().flush(timeout=3.0)
    payload = captured_traces[0]
    dumped = str(payload)
    assert "prompt_tokens" in dumped
    assert "gpt-4o-mini" in dumped


def test_client_enqueue_when_in_memory_queue_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When the in-memory queue is full, payloads should spill to the disk queue.

    :param monkeypatch: pytest monkeypatch fixture.
    :returns: None
    """
    root = Path(__file__).resolve().parents[1] / "tmp_test_queues"
    root.mkdir(exist_ok=True)
    sub = root / "fullq"
    sub.mkdir(exist_ok=True)

    try:
        configure(base_url="http://test", queue_dir=str(sub), disabled=False, reset_client=True)
        set_client(None)
        client = VerdictLensClient()

        def _raise_full(_payload: object) -> None:
            """
            Simulate a full in-memory queue.

            :param _payload: Ignored payload.
            :raises queue.Full: Always.
            """
            raise queue.Full

        monkeypatch.setattr(client._queue, "put_nowait", _raise_full)

        client.send_trace({"trace_id": "x", "name": "t", "status": "ok"})
        files = list(sub.glob("*.jsonl"))
        assert files, "expected spill-to-disk write"
    finally:
        shutil.rmtree(sub, ignore_errors=True)


# ---------------------------------------------------------------------------
# Data-flow lineage (Option B) — source_span_ids population
# ---------------------------------------------------------------------------

def test_source_span_ids_populated_when_output_passed_between_spans(
    captured_traces: List[Dict[str, Any]],
) -> None:
    """
    When the return value of one @trace span is directly passed as an argument
    to another @trace span, the downstream span's source_span_ids should
    contain the upstream span's span_id.
    """
    configure(base_url="http://test", disabled=False, reset_client=True)

    @trace(name="producer", span_type="agent")
    def producer() -> dict:
        return {"payload": "data from producer"}

    @trace(name="consumer", span_type="agent")
    def consumer(data: dict) -> str:
        return f"processed: {data['payload']}"

    @trace(name="pipeline", span_type="agent")
    def pipeline() -> str:
        result = producer()
        return consumer(result)

    pipeline()
    get_client().flush(timeout=3.0)

    assert len(captured_traces) == 1
    payload = captured_traces[0]

    # Find the producer and consumer spans
    spans = payload.get("spans", [])
    span_by_name = {s["name"]: s for s in spans}

    assert "producer" in span_by_name, f"expected producer span, got {list(span_by_name)}"
    assert "consumer" in span_by_name, f"expected consumer span, got {list(span_by_name)}"

    producer_id = span_by_name["producer"]["span_id"]
    consumer_source_ids = span_by_name["consumer"].get("source_span_ids", [])

    assert producer_id in consumer_source_ids, (
        f"consumer.source_span_ids {consumer_source_ids} should contain "
        f"producer span_id {producer_id}"
    )


def test_source_span_ids_empty_for_independent_spans(
    captured_traces: List[Dict[str, Any]],
) -> None:
    """
    When two spans do not share data (neither passes its output to the other),
    source_span_ids should be empty on both.
    """
    configure(base_url="http://test", disabled=False, reset_client=True)

    @trace(name="span_a", span_type="agent")
    def span_a() -> str:
        return "result_a"

    @trace(name="span_b", span_type="agent")
    def span_b() -> str:
        return "result_b"

    @trace(name="root", span_type="agent")
    def root() -> tuple:
        a = span_a()
        b = span_b()
        return (a, b)

    root()
    get_client().flush(timeout=3.0)

    spans = captured_traces[0].get("spans", [])
    span_by_name = {s["name"]: s for s in spans}

    # Neither span receives the other's output
    assert span_by_name["span_a"].get("source_span_ids", []) == []
    assert span_by_name["span_b"].get("source_span_ids", []) == []


@pytest.mark.asyncio
async def test_source_span_ids_async_pipeline(
    captured_traces: List[Dict[str, Any]],
) -> None:
    """
    Async pipeline: producer → consumer data-flow is tracked via source_span_ids.
    """
    configure(base_url="http://test", disabled=False, reset_client=True)

    @trace(name="async_producer", span_type="agent")
    async def async_producer() -> dict:
        await asyncio.sleep(0)
        return {"value": 42}

    @trace(name="async_consumer", span_type="agent")
    async def async_consumer(data: dict) -> int:
        await asyncio.sleep(0)
        return data["value"] * 2

    @trace(name="async_pipeline", span_type="agent")
    async def async_pipeline() -> int:
        result = await async_producer()
        return await async_consumer(result)

    await async_pipeline()
    get_client().flush(timeout=3.0)

    spans = captured_traces[0].get("spans", [])
    span_by_name = {s["name"]: s for s in spans}

    producer_id = span_by_name["async_producer"]["span_id"]
    consumer_source_ids = span_by_name["async_consumer"].get("source_span_ids", [])

    assert producer_id in consumer_source_ids
