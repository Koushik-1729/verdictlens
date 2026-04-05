"""
Pytest fixtures for VerdictLens SDK tests.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from verdictlens.client import VerdictLensClient, reset_client, set_client


@pytest.fixture(autouse=True)
def _reset_verdictlens_client() -> None:
    """
    Ensure tests do not leak background transport threads between cases.

    :yields: Nothing.
    """
    set_client(None)
    yield
    set_client(None)
    reset_client()


@pytest.fixture
def captured_traces(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """
    Capture trace payloads by short-circuiting the async HTTP transport.

    :param monkeypatch: pytest monkeypatch fixture.
    :returns: List mutated by background workers when traces are flushed.
    """
    import verdictlens.client as client_mod

    traces: List[Dict[str, Any]] = []

    async def _capture(self: VerdictLensClient, client: Any, payload: Dict[str, Any]) -> None:
        """
        Record payloads instead of performing HTTP.

        :param self: Active :class:`~verdictlens.client.VerdictLensClient` instance.
        :param client: Unused httpx client (kept for signature compatibility).
        :param payload: Trace JSON dict.
        :returns: None
        """
        _ = client
        traces.append(payload)

    monkeypatch.setattr(client_mod.VerdictLensClient, "_post_with_retries", _capture)
    return traces
