"""
Tests for safe serialization helpers.
"""

from __future__ import annotations

import pytest

from verdictlens.serializers import (
    default_cost_estimator,
    extract_openai_usage,
    merge_token_usage,
    safe_serialize,
)


def test_safe_serialize_primitives() -> None:
    """
    Primitives should round-trip as JSON-friendly values.

    :returns: None
    """
    assert safe_serialize(1) == 1
    assert safe_serialize("hi") == "hi"
    assert safe_serialize(None) is None


def test_safe_serialize_truncates_long_strings() -> None:
    """
    Long strings should be truncated with a marker.

    :returns: None
    """
    big = "x" * 100_000
    out = safe_serialize(big, max_string=50)
    assert isinstance(out, str)
    assert len(out) <= 50
    assert "truncated" in out


def test_safe_serialize_cycle_dict() -> None:
    """
    Cyclic structures should not recurse infinitely.

    :returns: None
    """
    d: dict = {}
    d["self"] = d
    out = safe_serialize(d, max_depth=20)
    assert isinstance(out, dict)
    assert out["self"] == "<cycle>"


def test_merge_token_usage() -> None:
    """
    Token usage dicts should sum field-wise.

    :returns: None
    """
    merged = merge_token_usage({"prompt_tokens": 1}, {"prompt_tokens": 2, "completion_tokens": 3})
    assert merged is not None
    assert merged["prompt_tokens"] == 3
    assert merged["completion_tokens"] == 3


def test_extract_openai_usage_dict() -> None:
    """
    OpenAI-style dict usage should normalize.

    :returns: None
    """
    u = extract_openai_usage({"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})
    assert u == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}


class _UsageObj:
    """
    Minimal usage object for extraction tests.
    """

    def __init__(self) -> None:
        """
        Initialize fixed token fields.

        :returns: None
        """
        self.prompt_tokens = 1
        self.completion_tokens = 2
        self.total_tokens = 3


def test_extract_openai_usage_object() -> None:
    """
    Object-shaped usage should normalize.

    :returns: None
    """
    u = extract_openai_usage(_UsageObj())
    assert u == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}


def test_default_cost_estimator_unknown_model() -> None:
    """
    Unknown models should yield no estimate.

    :returns: None
    """
    assert default_cost_estimator("unknown-model-xyz", {"prompt_tokens": 1000}) is None


def test_default_cost_estimator_known_model() -> None:
    """
    Known models should return a positive estimate when tokens are present.

    :returns: None
    """
    cost = default_cost_estimator(
        "gpt-4o-mini",
        {"prompt_tokens": 1_000_000, "completion_tokens": 0, "total_tokens": 1_000_000},
    )
    assert cost is not None
    assert cost > 0
