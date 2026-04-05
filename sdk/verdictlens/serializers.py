"""
Safe serialization of arbitrary Python values for trace payloads.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# Reasonable defaults to keep payloads bounded for the ingest pipeline.
_DEFAULT_MAX_STRING = 16_384
_DEFAULT_MAX_DEPTH = 8
_DEFAULT_MAX_ITEMS = 256


def _truncate_str(value: str, max_len: int) -> str:
    """
    Truncate a string with a clear suffix when too long.

    :param value: Original string.
    :param max_len: Maximum length including suffix overhead.
    :returns: Possibly truncated string.
    """
    if len(value) <= max_len:
        return value
    if max_len <= 32:
        return value[:max_len]
    suffix = f"...<truncated {len(value) - (max_len - 24)} chars>"
    keep = max_len - len(suffix)
    return value[:keep] + suffix


def safe_serialize(
    value: Any,
    *,
    max_string: int = _DEFAULT_MAX_STRING,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    max_items: int = _DEFAULT_MAX_ITEMS,
) -> Any:
    """
    Convert a value into a JSON-friendly structure with size limits.

    :param value: Any Python object.
    :param max_string: Maximum length for string nodes.
    :param max_depth: Maximum recursion depth.
    :param max_items: Maximum dict keys / list items per level.
    :returns: JSON-serializable structure or a descriptive fallback string.
    """
    try:
        return _safe_serialize_inner(
            value,
            max_string=max_string,
            max_depth=max_depth,
            max_items=max_items,
            _depth=0,
            _seen_ids=set(),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return {"_verdictlens_serialize_error": str(exc), "_type": type(value).__name__}


def _safe_serialize_inner(
    value: Any,
    *,
    max_string: int,
    max_depth: int,
    max_items: int,
    _depth: int,
    _seen_ids: set[int],
) -> Any:
    """
    Internal recursive serializer with cycle and depth guards.

    :param value: Node to serialize.
    :param max_string: String truncation budget.
    :param max_depth: Depth limit.
    :param max_items: Collection size limit per level.
    :param _depth: Current recursion depth.
    :param _seen_ids: Set of object ids on the active path.
    :returns: JSON-friendly value.
    """
    if _depth > max_depth:
        return f"<max_depth {max_depth}>"

    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float):
            if value != value:  # NaN
                return None
        return value

    if isinstance(value, str):
        return _truncate_str(value, max_string)

    if isinstance(value, bytes):
        try:
            decoded = value.decode("utf-8", errors="replace")
        except Exception:
            decoded = repr(value)
        return _truncate_str(decoded, max_string)

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.name

    if isinstance(value, type):
        return f"<type {value.__module__}.{value.__qualname__}>"

    obj_id = id(value)
    if isinstance(value, (list, tuple, dict, set)) and obj_id in _seen_ids:
        return "<cycle>"

    if is_dataclass(value) and not isinstance(value, type):
        try:
            as_dict = asdict(value)
            _seen_ids.add(obj_id)
            try:
                return _safe_serialize_inner(
                    as_dict,
                    max_string=max_string,
                    max_depth=max_depth,
                    max_items=max_items,
                    _depth=_depth + 1,
                    _seen_ids=_seen_ids,
                )
            finally:
                _seen_ids.discard(obj_id)
        except Exception:
            return _truncate_str(repr(value), max_string)

    if isinstance(value, BaseException):
        return {
            "type": type(value).__name__,
            "message": _truncate_str(str(value), max_string),
        }

    if isinstance(value, dict):
        _seen_ids.add(obj_id)
        try:
            out: Dict[str, Any] = {}
            for idx, (k, v) in enumerate(value.items()):
                if idx >= max_items:
                    out["_truncated_keys"] = len(value) - max_items
                    break
                key = str(k)
                if len(key) > 256:
                    key = key[:256] + "..."
                out[key] = _safe_serialize_inner(
                    v,
                    max_string=max_string,
                    max_depth=max_depth,
                    max_items=max_items,
                    _depth=_depth + 1,
                    _seen_ids=_seen_ids,
                )
            return out
        finally:
            _seen_ids.discard(obj_id)

    if isinstance(value, (list, tuple, set)):
        _seen_ids.add(obj_id)
        try:
            seq: List[Any] = []
            for idx, item in enumerate(value):
                if idx >= max_items:
                    seq.append({"_truncated_items": len(value) - max_items})
                    break
                seq.append(
                    _safe_serialize_inner(
                        item,
                        max_string=max_string,
                        max_depth=max_depth,
                        max_items=max_items,
                        _depth=_depth + 1,
                        _seen_ids=_seen_ids,
                    )
                )
            return seq
        finally:
            _seen_ids.discard(obj_id)

    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        try:
            dumped = value.model_dump()
            return _safe_serialize_inner(
                dumped,
                max_string=max_string,
                max_depth=max_depth,
                max_items=max_items,
                _depth=_depth + 1,
                _seen_ids=_seen_ids,
            )
        except Exception:
            pass

    if hasattr(value, "dict") and callable(getattr(value, "dict")):
        try:
            dumped = value.dict()
            return _safe_serialize_inner(
                dumped,
                max_string=max_string,
                max_depth=max_depth,
                max_items=max_items,
                _depth=_depth + 1,
                _seen_ids=_seen_ids,
            )
        except Exception:
            pass

    try:
        rep = repr(value)
    except Exception as exc:
        rep = f"<repr_error {exc}>"
    return _truncate_str(rep, max_string)


def dumps_json(payload: Any) -> str:
    """
    Serialize a JSON-friendly object to a compact UTF-8 JSON string.

    :param payload: Serializable object.
    :returns: JSON string.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def merge_token_usage(
    left: Optional[Dict[str, Optional[int]]],
    right: Optional[Dict[str, Optional[int]]],
) -> Optional[Dict[str, Optional[int]]]:
    """
    Sum two optional token usage dicts field-wise.

    :param left: Optional usage mapping.
    :param right: Optional usage mapping.
    :returns: Merged mapping or None if both empty.
    """
    if not left and not right:
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    out: Dict[str, Optional[int]] = {k: None for k in keys}
    for side in (left or {}), (right or {}):
        for k in keys:
            v = side.get(k)
            if v is None:
                continue
            if out[k] is None:
                out[k] = int(v)
            else:
                out[k] = int(out[k]) + int(v)
    if all(v is None for v in out.values()):
        return None
    return out


def extract_openai_usage(usage: Any) -> Optional[Dict[str, Optional[int]]]:
    """
    Normalize OpenAI ``usage`` objects to a plain dict.

    :param usage: Provider usage object or dict.
    :returns: Normalized dict or None.
    """
    if usage is None:
        return None
    if isinstance(usage, dict):
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        tt = usage.get("total_tokens")
        return {
            "prompt_tokens": int(pt) if pt is not None else None,
            "completion_tokens": int(ct) if ct is not None else None,
            "total_tokens": int(tt) if tt is not None else None,
        }
    pt = getattr(usage, "prompt_tokens", None)
    ct = getattr(usage, "completion_tokens", None)
    tt = getattr(usage, "total_tokens", None)
    try:
        return {
            "prompt_tokens": int(pt) if pt is not None else None,
            "completion_tokens": int(ct) if ct is not None else None,
            "total_tokens": int(tt) if tt is not None else None,
        }
    except Exception:
        return None


CostFn = Callable[[Optional[str], Dict[str, Optional[int]]], Optional[float]]


def default_cost_estimator(model: Optional[str], usage: Dict[str, Optional[int]]) -> Optional[float]:
    """
    Rough USD estimate for common OpenAI-style models (demo-quality, not billing-grade).

    :param model: Model name.
    :param usage: Token counts.
    :returns: Estimated USD or None if unknown.
    """
    if not model:
        return None
    m = model.lower()
    # Prices per 1M tokens (illustrative defaults; override via configure/metadata in prod).
    table: Dict[str, Tuple[float, float]] = {
        # OpenAI
        "gpt-4o": (5.0, 15.0),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4-turbo": (10.0, 30.0),
        "gpt-3.5-turbo": (0.50, 1.50),
        # Groq (hosted Llama / Mixtral)
        "llama-3.3-70b": (0.59, 0.79),
        "llama-3.1-70b": (0.59, 0.79),
        "llama-3.1-8b": (0.05, 0.08),
        "llama-3-70b": (0.59, 0.79),
        "llama-3-8b": (0.05, 0.08),
        "mixtral-8x7b": (0.24, 0.24),
        "gemma2-9b": (0.20, 0.20),
        # xAI Grok
        "grok-4": (3.0, 15.0),
        "grok-3": (3.0, 15.0),
        "grok-3-mini": (0.30, 0.50),
        "grok-2": (2.0, 10.0),
        # Anthropic Claude
        "claude-3.5-sonnet": (3.0, 15.0),
        "claude-3-opus": (15.0, 75.0),
        "claude-3-haiku": (0.25, 1.25),
        # Google Gemini
        "gemini-1.5-pro": (1.25, 5.0),
        "gemini-1.5-flash": (0.075, 0.30),
        "gemini-2.0-flash": (0.10, 0.40),
    }
    prices: Optional[Tuple[float, float]] = None
    for key, val in table.items():
        if key in m:
            prices = val
            break
    if prices is None:
        return None
    in_m = (usage.get("prompt_tokens") or 0) / 1_000_000.0
    out_m = (usage.get("completion_tokens") or 0) / 1_000_000.0
    return round(in_m * prices[0] + out_m * prices[1], 8)
