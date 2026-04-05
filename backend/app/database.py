"""
PostgreSQL database layer using SQLAlchemy.

Manages all transactional data: workspaces, API keys, prompt versions,
playground rate limits, and alert rules. ClickHouse remains the store
for traces, spans, and metrics.

Connection is controlled by ``VERDICTLENS_DATABASE_URL`` env var.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import get_settings

logger = logging.getLogger("verdictlens.database")


# ---------------------------------------------------------------------------
# ORM base & models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=False, server_default="")
    created_at = Column(String, nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    key_hash = Column(String, nullable=False, index=True)
    key_prefix = Column(String, nullable=False)
    created_at = Column(String, nullable=False)

    __table_args__ = (
        Index("idx_api_keys_workspace", "workspace_id"),
    )


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    model = Column(String, nullable=False, server_default="gpt-4o-mini")
    temperature = Column(Float, server_default="0.7")
    max_tokens = Column(Integer, server_default="1024")
    workspace_id = Column(String, nullable=False, server_default="default")
    version_number = Column(Integer, nullable=False, server_default="1")
    parent_id = Column(String, nullable=True)
    tags = Column(Text, nullable=False, server_default="[]")
    is_published = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(String, nullable=False)

    __table_args__ = (
        Index("idx_prompt_versions_workspace", "workspace_id"),
        Index("idx_prompt_versions_name", "name", "workspace_id"),
    )


class PlaygroundRateLimit(Base):
    __tablename__ = "playground_rate_limits"

    key = Column(String, primary_key=True)
    count = Column(Integer, nullable=False, server_default="0")
    window_start = Column(String, nullable=False)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    rule_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    condition = Column(String, nullable=False)
    window_minutes = Column(Integer, nullable=False, server_default="5")
    channels = Column(Text, nullable=False, server_default='["webhook"]')
    webhook_url = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    last_fired = Column(String, nullable=True)


class OnlineEvalRule(Base):
    __tablename__ = "online_eval_rules"

    rule_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    dataset_id = Column(String, nullable=False)
    workspace_id = Column(String, nullable=False)
    scorer_config = Column(Text, nullable=False, server_default='[]')
    filter_name = Column(String, nullable=True)  # only run on traces matching this name
    enabled = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(String, nullable=False)
    last_fired = Column(String, nullable=True)


class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(String, primary_key=True)
    trace_id = Column(String, nullable=False)
    span_id = Column(String, nullable=True)
    workspace_id = Column(String, nullable=False)
    thumbs = Column(String, nullable=True)   # 'up' | 'down' | None
    label = Column(String, nullable=True)    # e.g. 'correct', 'hallucination', 'needs_review'
    note = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)

    __table_args__ = (
        Index("idx_annotations_trace", "trace_id"),
        Index("idx_annotations_workspace", "workspace_id"),
    )


# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_engine(
            s.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def get_session() -> Session:
    """Create a new session. Caller is responsible for closing it."""
    factory = get_session_factory()
    return factory()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create all tables and seed the default workspace.

    Called once during application startup.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)

    s = get_settings()
    default_ws = s.default_workspace

    with get_session() as session:
        existing = session.query(Workspace).filter_by(slug=default_ws).first()
        if not existing:
            from uuid import uuid4
            session.add(Workspace(
                id=str(uuid4()),
                name="Default Workspace",
                slug=default_ws,
                description="Auto-created default workspace",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
            session.commit()

    logger.info("verdictlens: PostgreSQL tables ready")


def close_db() -> None:
    """Dispose of the engine connection pool."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionLocal = None
