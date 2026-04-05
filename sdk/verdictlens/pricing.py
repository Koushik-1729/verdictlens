"""
Pluggable cost estimation hooks (per-million token pricing tables).
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from verdictlens.serializers import CostFn, default_cost_estimator

_GLOBAL_COST_FN: Optional[CostFn] = None


def set_cost_estimator(fn: Optional[CostFn]) -> None:
    """
    Register a process-wide cost estimator used by the SDK.

    :param fn: Callable taking ``(model, usage_dict)`` or None to reset defaults.
    :returns: None
    """
    global _GLOBAL_COST_FN
    _GLOBAL_COST_FN = fn


def get_cost_estimator() -> CostFn:
    """
    Return the active cost estimator (custom or default).

    :returns: Cost estimation callable.
    """
    return _GLOBAL_COST_FN or default_cost_estimator


def estimate_cost_usd(model: Optional[str], usage: Dict[str, Optional[int]]) -> Optional[float]:
    """
    Estimate USD cost for a model call using the active estimator.

    :param model: Model identifier.
    :param usage: Token usage dict.
    :returns: Estimated USD or None.
    """
    try:
        return get_cost_estimator()(model, usage)
    except Exception:
        return None


def per_million_table(table: Dict[str, Tuple[float, float]]) -> CostFn:
    """
    Build a cost estimator from a ``model_substring -> (input_1m, output_1m)`` table.

    :param table: Mapping of substring keys to price-per-1M-token tuples (USD).
    :returns: Cost function compatible with :func:`set_cost_estimator`.
    """

    def _fn(model: Optional[str], usage: Dict[str, Optional[int]]) -> Optional[float]:
        """
        Compute cost for a model string and usage dict.

        :param model: Model name.
        :param usage: Token usage.
        :returns: Cost in USD or None.
        """
        if not model:
            return None
        m = model.lower()
        prices: Optional[Tuple[float, float]] = None
        for key, val in table.items():
            if key.lower() in m:
                prices = val
                break
        if prices is None:
            return None
        in_m = (usage.get("prompt_tokens") or 0) / 1_000_000.0
        out_m = (usage.get("completion_tokens") or 0) / 1_000_000.0
        return round(in_m * prices[0] + out_m * prices[1], 8)

    return _fn
