"""
Optional framework instrumentation helpers.

Each submodule documents its extra dependency (``pip install verdictlens[...]``).
"""

from __future__ import annotations

__all__ = [
    "instrument_openai_client",
    "VerdictLensLangChainCallbackHandler",
    "instrument_crewai_verbose",
    "instrument_autogen_llm",
    "VerdictLensLlamaIndexCallbackHandler",
]


def instrument_openai_client(client: object) -> object:
    """
    Patch an OpenAI client instance to emit LLM spans (lazy import).

    :param client: ``openai.OpenAI`` or ``openai.AsyncOpenAI`` instance.
    :returns: The same instance, patched in place.
    """
    from verdictlens.integrations.openai import instrument_openai_client as _impl

    return _impl(client)


class VerdictLensLangChainCallbackHandler:
    """
    LangChain callback handler proxy (lazy import).

    Subclassing happens in :mod:`verdictlens.integrations.langchain`.
    """

    def __new__(cls, *args: object, **kwargs: object) -> "VerdictLensLangChainCallbackHandler":
        """
        Construct the real handler class when LangChain is installed.

        :param args: Forwarded to the concrete handler.
        :param kwargs: Forwarded to the concrete handler.
        :returns: Concrete handler instance.
        """
        from verdictlens.integrations.langchain import VerdictLensLangChainCallbackHandler as Real

        return Real(*args, **kwargs)


def instrument_crewai_verbose() -> None:
    """
    Best-effort CrewAI hooks (lazy import).

    :returns: None
    """
    from verdictlens.integrations.crewai import instrument_crewai_verbose as _impl

    return _impl()


def instrument_autogen_llm() -> None:
    """
    Best-effort AutoGen client hooks (lazy import).

    :returns: None
    """
    from verdictlens.integrations.autogen import instrument_autogen_llm as _impl

    return _impl()


class VerdictLensLlamaIndexCallbackHandler:
    """
    LlamaIndex callback handler proxy (lazy import).
    """

    def __new__(cls, *args: object, **kwargs: object) -> "VerdictLensLlamaIndexCallbackHandler":
        """
        Construct the real LlamaIndex handler when installed.

        :param args: Forwarded to the concrete handler.
        :param kwargs: Forwarded to the concrete handler.
        :returns: Concrete handler instance.
        """
        from verdictlens.integrations.llamaindex import VerdictLensLlamaIndexCallbackHandler as Real

        return Real(*args, **kwargs)
