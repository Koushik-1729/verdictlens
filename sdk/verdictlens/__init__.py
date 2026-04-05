"""
VerdictLens Python SDK — lightweight tracing for AI agent workloads.

Public API: :func:`configure`, :func:`trace`, :class:`VerdictLensClient`,
auto-patchers (:func:`wrap_openai`, :func:`wrap_anthropic`, :func:`wrap_google`),
and optional framework instrumentation helpers under ``verdictlens.integrations``.
"""

from verdictlens import hub
from verdictlens.apiclient import VerdictLensAPIClient
from verdictlens.client import (
    VerdictLensClient,
    add_example,
    create_dataset,
    delete_example,
    get_client,
    list_datasets,
    list_examples,
    set_client,
)
from verdictlens.config import VerdictLensConfig, configure, get_config
from verdictlens.eval import evaluate
from verdictlens.patchers import wrap_anthropic, wrap_google, wrap_openai
from verdictlens.pricing import per_million_table, set_cost_estimator
from verdictlens.schema import SCHEMA_VERSION
from verdictlens.trace import get_current_span, record_child_span, trace

__all__ = [
    "VerdictLensAPIClient",
    "VerdictLensClient",
    "hub",
    "VerdictLensConfig",
    "SCHEMA_VERSION",
    "add_example",
    "configure",
    "create_dataset",
    "delete_example",
    "evaluate",
    "get_client",
    "get_config",
    "get_current_span",
    "list_datasets",
    "list_examples",
    "per_million_table",
    "record_child_span",
    "set_client",
    "set_cost_estimator",
    "trace",
    "wrap_anthropic",
    "wrap_google",
    "wrap_openai",
]

__version__ = "0.2.0"
