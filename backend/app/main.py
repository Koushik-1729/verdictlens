"""
FastAPI application factory for the VerdictLens backend.

``create_app()`` wires together:
- PostgreSQL schema bootstrap (workspaces, API keys, prompts, alerts)
- ClickHouse schema bootstrap (traces, spans, metrics)
- Redis-backed WebSocket pub/sub
- Optional API-key auth (bcrypt, in-memory)
- Alert evaluation background task
- CORS middleware
- All API routes
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.alerts import alert_evaluation_loop, close_alerts_db
from app.auth import close_auth_db, init_auth
from app.clickhouse import close_client, ensure_schema
from app.database import close_db, init_db
from app.live import manager
from app.routes import router
from app.settings import get_settings

logger = logging.getLogger("verdictlens")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Startup / shutdown lifecycle hook.

    :param app: FastAPI application instance.
    :yields: Control back to the framework while the app is running.
    """
    settings = get_settings()

    # PostgreSQL — workspaces, API keys, prompts, alerts
    try:
        init_db()
        logger.info("verdictlens: PostgreSQL schema ready")
    except Exception as exc:
        logger.error(
            "verdictlens: PostgreSQL unavailable at startup (%s). "
            "Auth, workspaces, and prompts will fail until PostgreSQL is reachable.",
            exc,
        )

    # Auth (bcrypt hash in memory, or open mode)
    init_auth()

    # ClickHouse
    try:
        ensure_schema(settings)
        logger.info("verdictlens: ClickHouse schema ready")
    except Exception as exc:
        logger.error(
            "verdictlens: ClickHouse unavailable at startup (%s). "
            "Traces will fail until ClickHouse is reachable.",
            exc,
        )

    # Redis live feed
    await manager.start(settings.redis_url)

    # Alert evaluation background task
    alert_task = asyncio.create_task(alert_evaluation_loop())

    yield

    # Shutdown
    alert_task.cancel()
    try:
        await alert_task
    except asyncio.CancelledError:
        pass
    await manager.stop()
    close_client()
    close_alerts_db()
    close_auth_db()
    close_db()
    logger.info("verdictlens: shutdown complete")


def create_app() -> FastAPI:
    """
    Build and configure the FastAPI application.

    :returns: Fully wired FastAPI app.
    """
    settings = get_settings()
    app = FastAPI(
        title="VerdictLens API",
        description="Observability backend for AI agents — trace ingestion, query, and live streaming.",
        version=__version__,
        lifespan=_lifespan,
        debug=settings.debug,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app


app = create_app()
