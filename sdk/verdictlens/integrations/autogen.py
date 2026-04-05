"""
AutoGen (``pyautogen``) integration.

AutoGen typically routes model calls through OpenAI-compatible clients; the most
reliable instrumentation path is patching the underlying OpenAI client.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("verdictlens.integrations.autogen")


def _find_openai_client(obj: Any, depth: int = 0, max_depth: int = 4) -> Optional[Any]:
    """
    Best-effort search for an OpenAI-like client on nested AutoGen objects.

    :param obj: Root object to inspect.
    :param depth: Current recursion depth.
    :param max_depth: Maximum recursion depth.
    :returns: A client instance if found.
    """
    if depth > max_depth or obj is None:
        return None
    mod = type(obj).__module__
    name = type(obj).__name__
    if "openai" in mod and "OpenAI" in name:
        return obj
    for attr in ("_client", "client", "openai_client", "llm_client"):
        child = getattr(obj, attr, None)
        found = _find_openai_client(child, depth + 1, max_depth)
        if found is not None:
            return found
    return None


def instrument_autogen_llm(agent_or_client: Optional[Any] = None) -> None:
    """
    Attempt to patch OpenAI chat calls for an AutoGen agent or client.

    If ``agent_or_client`` is omitted, this function attempts to locate a global
    client on commonly used AutoGen classes (best effort, version dependent).

    :param agent_or_client: Optional AutoGen agent / client object.
    :returns: None
    """
    try:
        import autogen  # noqa: F401
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("verdictlens AutoGen integration requires `pip install pyautogen`") from exc

    from verdictlens.integrations.openai import instrument_openai_client

    target = agent_or_client
    if target is None:
        logger.info(
            "verdictlens: instrument_autogen_llm() called without a concrete client/agent; "
            "pass your AutoGen agent or underlying OpenAI client for reliable patching."
        )
        return

    client = _find_openai_client(target)
    if client is None and hasattr(target, "client"):
        client = getattr(target, "client", None)
    if client is None:
        logger.warning(
            "verdictlens: could not locate an OpenAI client on %r; "
            "call instrument_openai_client(openai_client) explicitly.",
            target,
        )
        return
    instrument_openai_client(client)
