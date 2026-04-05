"""
Prompt Playground — live editor to modify prompts/params, run, iterate.

Safety layer enforced before every execution:
- Token clamping to ``PLAYGROUND_MAX_TOKENS``
- Rate limiting per IP/workspace
- Cost estimation guard against ``PLAYGROUND_MAX_COST_USD``
- Prompt sanitization (strip null bytes, limit length)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import func as sa_func

from app.database import PlaygroundRateLimit, PromptVersion, get_session
from app.models import (
    PlaygroundRunIn,
    PlaygroundRunOut,
    PromptHubEntry,
    PromptUsageStats,
    PromptVersionHistory,
    PromptVersionIn,
    PromptVersionOut,
)
from app.settings import Settings, get_settings

logger = logging.getLogger("verdictlens.playground")


# ---------------------------------------------------------------------------
# Safety layer
# ---------------------------------------------------------------------------

_MAX_PROMPT_CHARS = 100_000

_COST_PER_MILLION: Dict[str, Tuple[float, float]] = {
    "gpt-4o": (5.0, 15.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-3.5-turbo": (0.50, 1.50),
    "llama-3.3-70b": (0.59, 0.79),
    "mixtral-8x7b": (0.24, 0.24),
    "grok-3": (3.0, 15.0),
    "grok-3-mini": (0.30, 0.50),
    "claude-3-5-sonnet-20241022": (3.0, 15.0),
    "claude-3-haiku": (0.25, 1.25),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
}


def sanitize_prompt(text: str) -> str:
    """Strip null bytes, control characters, and clamp length."""
    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text[:_MAX_PROMPT_CHARS]


def clamp_tokens(requested: int, settings: Settings) -> int:
    """Clamp max_tokens to the configured ceiling."""
    return min(max(1, requested), settings.playground_max_tokens)


def estimate_cost(model: str, prompt_tokens: int, max_completion: int) -> float:
    """Estimate worst-case cost in USD for a playground run."""
    prices = _COST_PER_MILLION.get(model)
    if not prices:
        for key, val in _COST_PER_MILLION.items():
            if key in model.lower():
                prices = val
                break
    if not prices:
        prices = (5.0, 15.0)

    input_cost = (prompt_tokens / 1_000_000) * prices[0]
    output_cost = (max_completion / 1_000_000) * prices[1]
    return round(input_cost + output_cost, 6)


def check_rate_limit(key: str, settings: Settings) -> bool:
    """
    Check and increment rate limit counter.

    Returns True if within limits, False if exceeded.
    """
    now = datetime.now(timezone.utc).isoformat()
    window_seconds = settings.playground_rate_window

    with get_session() as session:
        row = session.query(PlaygroundRateLimit).filter_by(key=key).first()
        if row:
            window_start = datetime.fromisoformat(row.window_start)
            elapsed = (datetime.now(timezone.utc) - window_start).total_seconds()
            if elapsed > window_seconds:
                row.count = 1
                row.window_start = now
                session.commit()
                return True
            if row.count >= settings.playground_rate_limit:
                return False
            row.count += 1
            session.commit()
            return True
        else:
            session.add(PlaygroundRateLimit(key=key, count=1, window_start=now))
            session.commit()
            return True


def validate_run(req: PlaygroundRunIn, settings: Settings, rate_key: str) -> Optional[str]:
    """
    Run all safety checks. Returns an error message string if any check fails, None if OK.
    """
    if not req.prompt.strip():
        return "Prompt cannot be empty"

    req.max_tokens = clamp_tokens(req.max_tokens, settings)

    prompt_tokens_est = len(req.prompt) // 4 + 50
    est_cost = estimate_cost(req.model, prompt_tokens_est, req.max_tokens)
    if est_cost > settings.playground_max_cost_usd:
        return f"Estimated cost ${est_cost:.4f} exceeds limit ${settings.playground_max_cost_usd:.2f}"

    if not check_rate_limit(rate_key, settings):
        return f"Rate limit exceeded: max {settings.playground_rate_limit} runs per {settings.playground_rate_window}s"

    return None


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_playground_run(req: PlaygroundRunIn, workspace_id: str) -> PlaygroundRunOut:
    """
    Execute a playground prompt against the LLM.

    Imports provider routing from replay.py (same infrastructure).
    """
    from app.replay import _execute_llm_call

    prompt = sanitize_prompt(req.prompt)
    messages: List[Dict[str, str]] = []
    if req.system_message:
        messages.append({"role": "system", "content": sanitize_prompt(req.system_message)})
    messages.append({"role": "user", "content": prompt})

    messages_input: Dict[str, Any] = {
        "messages": messages,
        "model": req.model,
        "temperature": req.temperature,
    }

    try:
        output, error, latency_ms, cost_usd, total_tokens, token_detail = _execute_llm_call(
            model=req.model,
            original_input=None,
            new_input=messages_input,
        )
    except ValueError as exc:
        return PlaygroundRunOut(error=str(exc), model=req.model)
    except Exception as exc:
        logger.error("verdictlens: playground execution failed: %s", exc, exc_info=True)
        return PlaygroundRunOut(error=f"Execution failed: {type(exc).__name__}: {exc}", model=req.model)

    if error:
        error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        return PlaygroundRunOut(
            error=error_msg,
            model=req.model,
            latency_ms=latency_ms,
        )

    content = output
    if isinstance(output, dict):
        content = output.get("content", str(output))

    return PlaygroundRunOut(
        output=str(content) if content is not None else None,
        model=req.model,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        prompt_tokens=token_detail.get("prompt_tokens") or 0,
        completion_tokens=token_detail.get("completion_tokens") or 0,
        total_tokens=total_tokens,
    )


# ---------------------------------------------------------------------------
# Prompt versioning CRUD
# ---------------------------------------------------------------------------

def _row_to_version(r: PromptVersion) -> PromptVersionOut:
    """Convert a SQLAlchemy PromptVersion row to PromptVersionOut."""
    tags: List[str] = []
    try:
        tags = json.loads(r.tags) if r.tags else []
    except (json.JSONDecodeError, TypeError):
        pass
    return PromptVersionOut(
        id=r.id, name=r.name, content=r.content, model=r.model,
        temperature=r.temperature, max_tokens=r.max_tokens, workspace_id=r.workspace_id,
        version_number=r.version_number, parent_id=r.parent_id, tags=tags,
        is_published=bool(r.is_published), created_at=r.created_at,
    )


def save_prompt_version(
    req: PromptVersionIn,
    workspace_id: str,
) -> PromptVersionOut:
    """Save a new prompt version to PostgreSQL."""
    version_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_session() as session:
        version_number = 1
        if req.parent_id:
            row = (
                session.query(sa_func.max(PromptVersion.version_number))
                .filter_by(name=req.name, workspace_id=workspace_id)
                .scalar()
            )
            if row:
                version_number = row + 1

        tags_json = json.dumps(req.tags)
        pv = PromptVersion(
            id=version_id, name=req.name, content=req.content, model=req.model,
            temperature=req.temperature, max_tokens=req.max_tokens,
            workspace_id=workspace_id, version_number=version_number,
            parent_id=req.parent_id, tags=tags_json, is_published=False,
            created_at=now,
        )
        session.add(pv)
        session.commit()

    return PromptVersionOut(
        id=version_id, name=req.name, content=req.content, model=req.model,
        temperature=req.temperature, max_tokens=req.max_tokens,
        workspace_id=workspace_id, version_number=version_number,
        parent_id=req.parent_id, tags=req.tags, is_published=False,
        created_at=now,
    )


def list_prompt_versions(workspace_id: str) -> List[PromptVersionOut]:
    """List all prompt versions for a workspace, newest first."""
    with get_session() as session:
        rows = (
            session.query(PromptVersion)
            .filter_by(workspace_id=workspace_id)
            .order_by(PromptVersion.created_at.desc())
            .all()
        )
        return [_row_to_version(r) for r in rows]


def get_prompt_version(version_id: str, workspace_id: str) -> Optional[PromptVersionOut]:
    """Fetch a single prompt version."""
    with get_session() as session:
        r = (
            session.query(PromptVersion)
            .filter_by(id=version_id, workspace_id=workspace_id)
            .first()
        )
        if not r:
            return None
        return _row_to_version(r)


def delete_prompt_version(version_id: str, workspace_id: str) -> bool:
    """Delete a prompt version."""
    with get_session() as session:
        count = (
            session.query(PromptVersion)
            .filter_by(id=version_id, workspace_id=workspace_id)
            .delete()
        )
        session.commit()
        return count > 0


# ---------------------------------------------------------------------------
# Prompt Hub — Phase 5
# ---------------------------------------------------------------------------

def get_version_history(name: str, workspace_id: str) -> PromptVersionHistory:
    """Get the full version history for a named prompt."""
    with get_session() as session:
        rows = (
            session.query(PromptVersion)
            .filter_by(name=name, workspace_id=workspace_id)
            .order_by(PromptVersion.version_number.desc())
            .all()
        )
        versions = [_row_to_version(r) for r in rows]

    return PromptVersionHistory(
        name=name,
        workspace_id=workspace_id,
        versions=versions,
        total_versions=len(versions),
        latest_version=versions[0] if versions else None,
    )


def publish_prompt(version_id: str, workspace_id: str) -> bool:
    """Mark a prompt version as published."""
    with get_session() as session:
        count = (
            session.query(PromptVersion)
            .filter_by(id=version_id, workspace_id=workspace_id)
            .update({"is_published": True})
        )
        session.commit()
        return count > 0


def unpublish_prompt(version_id: str, workspace_id: str) -> bool:
    """Unpublish a prompt version."""
    with get_session() as session:
        count = (
            session.query(PromptVersion)
            .filter_by(id=version_id, workspace_id=workspace_id)
            .update({"is_published": False})
        )
        session.commit()
        return count > 0


def list_published_prompts(workspace_id: Optional[str] = None) -> List[PromptHubEntry]:
    """
    List all published prompts across workspaces (or for a specific workspace).

    Groups by name and returns the latest published version for each.
    """
    with get_session() as session:
        query = session.query(PromptVersion).filter_by(is_published=True)
        if workspace_id:
            query = query.filter_by(workspace_id=workspace_id)
        rows = query.order_by(PromptVersion.name, PromptVersion.version_number.desc()).all()

        seen_names: Dict[str, PromptHubEntry] = {}
        for r in rows:
            v = _row_to_version(r)
            key = f"{v.workspace_id}:{v.name}"
            if key not in seen_names:
                total = (
                    session.query(sa_func.count(PromptVersion.id))
                    .filter_by(name=v.name, workspace_id=v.workspace_id)
                    .scalar()
                )
                seen_names[key] = PromptHubEntry(
                    id=v.id, name=v.name, content=v.content, model=v.model,
                    temperature=v.temperature, max_tokens=v.max_tokens,
                    workspace_id=v.workspace_id, version_number=v.version_number,
                    tags=v.tags, created_at=v.created_at,
                    total_versions=total or 1, usage_count=0,
                )

    return list(seen_names.values())


def get_prompt_usage_stats(prompt_name: str, workspace_id: str) -> PromptUsageStats:
    """
    Get usage statistics for a named prompt by querying ClickHouse spans
    that reference prompt_id matching any version of this prompt.
    """
    with get_session() as session:
        version_ids = (
            session.query(PromptVersion.id)
            .filter_by(name=prompt_name, workspace_id=workspace_id)
            .all()
        )

    if not version_ids:
        return PromptUsageStats(prompt_name=prompt_name)

    ids = [r[0] for r in version_ids]

    try:
        from app.clickhouse import _get_client
        s = get_settings()
        client = _get_client(s)
        db = s.ch_database

        placeholders = ", ".join(f"'{pid}'" for pid in ids)
        sql = (
            f"SELECT count() AS runs, "
            f"sum(total_tokens) AS tok, "
            f"sum(cost_usd) AS cost, "
            f"avg(latency_ms) AS lat, "
            f"max(created_at) AS last_used "
            f"FROM {db}.spans "
            f"WHERE prompt_id IN ({placeholders}) "
            f"AND workspace_id = {{ws:String}}"
        )
        result = client.query(sql, parameters={"ws": workspace_id})
        if result.result_rows and result.result_rows[0][0] > 0:
            row = result.result_rows[0]
            return PromptUsageStats(
                prompt_name=prompt_name,
                total_runs=int(row[0]),
                total_tokens=int(row[1] or 0),
                total_cost_usd=round(float(row[2] or 0), 6),
                avg_latency_ms=round(float(row[3] or 0), 2),
                last_used=str(row[4]) if row[4] else None,
            )
    except Exception as exc:
        logger.debug("verdictlens: prompt usage stats query failed: %s", exc)

    return PromptUsageStats(prompt_name=prompt_name)


def promote_version(version_id: str, workspace_id: str) -> Optional[PromptVersionOut]:
    """
    Promote an older version — creates a new version with the same content
    as the specified version, effectively making it the latest.
    """
    source = get_prompt_version(version_id, workspace_id)
    if not source:
        return None

    return save_prompt_version(
        PromptVersionIn(
            name=source.name,
            content=source.content,
            model=source.model,
            temperature=source.temperature,
            max_tokens=source.max_tokens,
            parent_id=source.id,
            tags=source.tags,
        ),
        workspace_id,
    )


def close_playground_db() -> None:
    """No-op — connection pool is managed by database.py engine."""
    pass
