"""
CrewAI integration helpers.

CrewAI versions differ in how they expose callbacks; this module provides a
drop-in callback handler (reusing the LangChain-compatible path when CrewAI
is built on LangChain) and a no-op ``instrument_crewai_verbose`` hook reserved
for future monkey-patching.
"""

from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger("verdictlens.integrations.crewai")


def crew_callback_handlers(trace_name_prefix: str = "crewai") -> List[Any]:
    """
    Build callback handlers suitable for passing into Crew/Agent constructors on supported versions.

    :param trace_name_prefix: Prefix for trace names in the UI.
    :returns: A list containing an :class:`~verdictlens.integrations.langchain.VerdictLensLangChainCallbackHandler`.
    """
    from verdictlens.integrations.langchain import VerdictLensLangChainCallbackHandler

    return [VerdictLensLangChainCallbackHandler(trace_name_prefix=trace_name_prefix)]


def instrument_crewai_verbose() -> None:
    """
    Reserved hook for automatic CrewAI instrumentation.

    CrewAI's public callback surface has shifted across releases; today the
    supported path is to pass :func:`crew_callback_handlers` into your Crew
    configuration where callbacks are accepted.

    :returns: None
    """
    try:
        import crewai  # noqa: F401
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("verdictlens CrewAI integration requires `pip install crewai`") from exc

    logger.info(
        "verdictlens: CrewAI auto-instrumentation is not enabled automatically. "
        "Pass handlers from verdictlens.integrations.crewai.crew_callback_handlers() "
        "to your Crew/LLM configuration when supported by your CrewAI version."
    )
