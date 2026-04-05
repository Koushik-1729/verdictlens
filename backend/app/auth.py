"""
API-key authentication for VerdictLens with workspace resolution.

Two authentication modes coexist:

1. **Legacy single key** — ``VERDICTLENS_API_KEY`` env var. Simple shared secret,
   hashed with bcrypt at startup. Maps to the default workspace.
2. **Per-workspace keys** — stored in PostgreSQL (``api_keys`` table), hashed with
   SHA-256. Each key is tied to a specific workspace.

When auth is disabled (no env key, ``REQUIRE_AUTH=false``), all requests
are routed to the default workspace.

The resolved ``workspace_id`` is injected into ``request.state.workspace_id``
by the ``resolve_workspace`` dependency so downstream route handlers can
read it without touching auth logic.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Dict, Optional, Tuple

import bcrypt
from fastapi import Header, HTTPException, Request

from app.database import ApiKey, Workspace, get_session
from app.settings import get_settings

logger = logging.getLogger("verdictlens.auth")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_KEY_HASH: Optional[bytes] = None
_AUTH_ENABLED: bool = False
_REQUIRE_AUTH: bool = False

# In-process cache: key_hash -> (workspace_id, expiry_monotonic)
# Only positive hits are cached (valid keys). TTL = 60 s.
_KEY_CACHE: Dict[str, Tuple[str, float]] = {}
_KEY_CACHE_TTL: float = 60.0


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_auth() -> None:
    """
    Read auth config from settings and prepare bcrypt hash for the legacy key.

    Call once during application startup (lifespan hook).
    """
    global _KEY_HASH, _AUTH_ENABLED, _REQUIRE_AUTH

    settings = get_settings()
    _REQUIRE_AUTH = settings.require_auth

    raw_key = (settings.api_key or "").strip()

    if not raw_key:
        _AUTH_ENABLED = False
        _KEY_HASH = None
        if _REQUIRE_AUTH:
            logger.warning(
                "REQUIRE_AUTH is true but no VERDICTLENS_API_KEY is set. "
                "Only per-workspace API keys from PostgreSQL will be accepted."
            )
        else:
            logger.warning(
                "\u26a0\ufe0f VerdictLens running without authentication. "
                "Set VERDICTLENS_API_KEY to enable auth."
            )
        return

    _KEY_HASH = bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt())
    _AUTH_ENABLED = True
    logger.info("VerdictLens running with API key auth enabled.")


# ---------------------------------------------------------------------------
# Key verification
# ---------------------------------------------------------------------------

def _verify_legacy(raw_key: str) -> bool:
    """Constant-time bcrypt check against the env-var key."""
    if _KEY_HASH is None:
        return False
    return bcrypt.checkpw(raw_key.encode("utf-8"), _KEY_HASH)


def _verify_workspace_key(raw_key: str) -> Optional[str]:
    """
    Look up a per-workspace API key in PostgreSQL, with a 60-second in-process cache.

    Only successful lookups are cached so newly created keys are visible immediately.

    :returns: workspace_id if the key is valid, None otherwise.
    """
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    cached = _KEY_CACHE.get(key_hash)
    if cached is not None:
        workspace_id, expires_at = cached
        if time.monotonic() < expires_at:
            return workspace_id
        del _KEY_CACHE[key_hash]

    try:
        with get_session() as session:
            row = session.query(ApiKey.workspace_id).filter_by(key_hash=key_hash).first()
            if row:
                _KEY_CACHE[key_hash] = (row[0], time.monotonic() + _KEY_CACHE_TTL)
                return row[0]
    except Exception as exc:
        logger.debug("verdictlens: PostgreSQL key lookup error: %s", exc)
    return None


def _extract_key(
    x_verdictlens_key: Optional[str],
    authorization: Optional[str],
) -> Optional[str]:
    """Extract the raw key from headers."""
    if x_verdictlens_key:
        return x_verdictlens_key.strip()
    if authorization:
        return authorization.removeprefix("Bearer ").strip()
    return None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def optional_auth(
    request: Request,
    x_verdictlens_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    x_verdictlens_workspace: Optional[str] = Header(None),
    x_verdictlens_project: Optional[str] = Header(None),
) -> None:
    """
    Authenticate the request and inject workspace_id into request.state.

    Resolution order:
    1. Per-workspace PostgreSQL key -> workspace from DB
    2. Legacy env-var key -> default workspace
    3. No key + auth not required -> default workspace
    4. No key + auth required -> 401
    """
    settings = get_settings()
    default_ws = settings.default_workspace

    raw = _extract_key(x_verdictlens_key, authorization)

    if raw:
        ws_from_db = _verify_workspace_key(raw)
        if ws_from_db:
            request.state.workspace_id = x_verdictlens_workspace or ws_from_db
            request.state.project_name = x_verdictlens_project or ""
            return

        if _AUTH_ENABLED and _verify_legacy(raw):
            request.state.workspace_id = x_verdictlens_workspace or default_ws
            request.state.project_name = x_verdictlens_project or ""
            return

        raise HTTPException(status_code=401, detail="Invalid API key")

    if _REQUIRE_AUTH or _AUTH_ENABLED:
        raise HTTPException(status_code=401, detail="Missing API key")

    request.state.workspace_id = x_verdictlens_workspace or default_ws
    request.state.project_name = x_verdictlens_project or ""


async def resolve_workspace(request: Request) -> str:
    """
    Read the workspace_id that was injected by ``optional_auth``.
    """
    return getattr(request.state, "workspace_id", get_settings().default_workspace)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def verify_key(raw_key: str) -> bool:
    """
    Public wrapper for key verification (used by WebSocket auth).

    Returns True if the key is valid against either legacy or PostgreSQL store.
    """
    if not _AUTH_ENABLED and not _REQUIRE_AUTH:
        return True
    if _verify_legacy(raw_key):
        return True
    if _verify_workspace_key(raw_key) is not None:
        return True
    return False


def is_auth_enabled() -> bool:
    """Return True when API key auth is active."""
    return _AUTH_ENABLED or _REQUIRE_AUTH


# ---------------------------------------------------------------------------
# Workspace CRUD (used by routes)
# ---------------------------------------------------------------------------

def create_workspace(*, workspace_id: str, name: str, slug: str, description: str, created_at: str) -> None:
    """Insert a workspace row into PostgreSQL."""
    with get_session() as session:
        session.add(Workspace(
            id=workspace_id, name=name, slug=slug,
            description=description, created_at=created_at,
        ))
        session.commit()


def list_workspaces() -> list:
    """Return all workspaces as dicts."""
    with get_session() as session:
        rows = session.query(Workspace).order_by(Workspace.created_at).all()
        return [
            {"id": r.id, "name": r.name, "slug": r.slug,
             "description": r.description, "created_at": r.created_at}
            for r in rows
        ]


def get_workspace(workspace_id: str) -> Optional[dict]:
    """Fetch a single workspace by ID."""
    with get_session() as session:
        r = session.query(Workspace).filter_by(id=workspace_id).first()
        if not r:
            return None
        return {"id": r.id, "name": r.name, "slug": r.slug,
                "description": r.description, "created_at": r.created_at}


def create_api_key(*, key_id: str, name: str, workspace_id: str, key_hash: str, key_prefix: str, created_at: str) -> None:
    """Insert an API key row into PostgreSQL."""
    with get_session() as session:
        session.add(ApiKey(
            id=key_id, name=name, workspace_id=workspace_id,
            key_hash=key_hash, key_prefix=key_prefix, created_at=created_at,
        ))
        session.commit()


def list_api_keys(workspace_id: str) -> list:
    """Return all API keys for a workspace (without hashes)."""
    with get_session() as session:
        rows = (
            session.query(ApiKey)
            .filter_by(workspace_id=workspace_id)
            .order_by(ApiKey.created_at)
            .all()
        )
        return [
            {"id": r.id, "name": r.name, "workspace_id": r.workspace_id,
             "key_prefix": r.key_prefix, "created_at": r.created_at}
            for r in rows
        ]


def delete_api_key(key_id: str, workspace_id: str) -> bool:
    """Delete an API key. Returns True if a row was deleted."""
    with get_session() as session:
        row = session.query(ApiKey.key_hash).filter_by(id=key_id, workspace_id=workspace_id).first()
        count = (
            session.query(ApiKey)
            .filter_by(id=key_id, workspace_id=workspace_id)
            .delete()
        )
        session.commit()
        if row:
            _KEY_CACHE.pop(row[0], None)
        return count > 0


def close_auth_db() -> None:
    """No-op — connection pool is managed by database.py engine."""
    pass
