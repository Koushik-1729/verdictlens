"""
ClickHouse client, schema migrations, and query helpers for VerdictLens.

Uses ``clickhouse-connect`` which speaks the ClickHouse HTTP interface
(port 8123 by default) and works in both sync and threaded contexts.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from app.models import (
    GroupedCount,
    LatencyPercentilesPoint,
    MetricsResponse,
    MonitoringCostTokens,
    MonitoringLLM,
    MonitoringRunTypes,
    MonitoringTools,
    MonitoringTraces,
    SpanIn,
    SpanOut,
    TimeSeriesPoint,
    TokenUsageOut,
    TraceDetailOut,
    TraceIn,
    TraceListResponse,
    TraceOut,
)
from app.settings import Settings, get_settings

logger = logging.getLogger("verdictlens.clickhouse")

# ---------------------------------------------------------------------------
# DDL — initial table creation
# ---------------------------------------------------------------------------

_CREATE_DB = "CREATE DATABASE IF NOT EXISTS {db}"

_CREATE_TRACES = """
CREATE TABLE IF NOT EXISTS {db}.traces (
    trace_id          String,
    name              String,
    start_time        DateTime64(3, 'UTC'),
    end_time          Nullable(DateTime64(3, 'UTC')),
    latency_ms        Nullable(Float64),
    status            LowCardinality(String)   DEFAULT 'success',
    framework         Nullable(String),
    model             Nullable(String),
    input             Nullable(String),
    output            Nullable(String),
    decision          Nullable(String),
    confidence_score  Nullable(Float64),
    prompt_tokens     Nullable(Int64),
    completion_tokens Nullable(Int64),
    total_tokens      Nullable(Int64),
    cost_usd          Nullable(Float64),
    error             Nullable(String),
    span_count        UInt32                    DEFAULT 0,
    metadata          String                    DEFAULT '{{}}',
    inserted_at       DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (start_time, trace_id)
PARTITION BY toYYYYMM(start_time)
"""

_CREATE_SPANS = """
CREATE TABLE IF NOT EXISTS {db}.spans (
    span_id           String,
    parent_span_id    Nullable(String),
    trace_id          String,
    name              String,
    span_type         LowCardinality(String)   DEFAULT 'other',
    start_time        DateTime64(3, 'UTC'),
    end_time          Nullable(DateTime64(3, 'UTC')),
    latency_ms        Nullable(Float64),
    model             Nullable(String),
    input             Nullable(String),
    output            Nullable(String),
    decision          Nullable(String),
    confidence_score  Nullable(Float64),
    prompt_tokens     Nullable(Int64),
    completion_tokens Nullable(Int64),
    total_tokens      Nullable(Int64),
    cost_usd          Nullable(Float64),
    error             Nullable(String),
    metadata          String                    DEFAULT '{{}}',
    inserted_at       DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (trace_id, start_time, span_id)
PARTITION BY toYYYYMM(start_time)
"""

# ---------------------------------------------------------------------------
# DDL — Dataset Builder + Evaluation Engine (Phase 1+2)
# ---------------------------------------------------------------------------

_CREATE_DATASETS = """
CREATE TABLE IF NOT EXISTS {db}.datasets (
    id                String,
    name              String,
    description       String                    DEFAULT '',
    workspace_id      String                    DEFAULT 'default',
    project_name      String                    DEFAULT '',
    created_at        DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (workspace_id, created_at, id)
"""

_CREATE_DATASET_EXAMPLES = """
CREATE TABLE IF NOT EXISTS {db}.dataset_examples (
    id                String,
    dataset_id        String,
    inputs            String                    DEFAULT '{{}}',
    outputs           String                    DEFAULT '{{}}',
    expected          String                    DEFAULT '{{}}',
    metadata          String                    DEFAULT '{{}}',
    source_trace_id   Nullable(String),
    source_span_id    Nullable(String),
    created_at        DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (dataset_id, created_at, id)
"""

_CREATE_EVALUATIONS = """
CREATE TABLE IF NOT EXISTS {db}.evaluations (
    id                String,
    name              String,
    dataset_id        String,
    workspace_id      String                    DEFAULT 'default',
    scorer_config     String                    DEFAULT '{{}}',
    mode              LowCardinality(String)    DEFAULT 'replay',
    status            LowCardinality(String)    DEFAULT 'pending',
    created_at        DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC'),
    completed_at      Nullable(DateTime64(3, 'UTC'))
) ENGINE = MergeTree()
ORDER BY (workspace_id, created_at, id)
"""

_CREATE_EVALUATION_RESULTS = """
CREATE TABLE IF NOT EXISTS {db}.evaluation_results (
    id                String,
    eval_id           String,
    example_id        String,
    score             Float32                   DEFAULT 0.0,
    passed            UInt8                     DEFAULT 0,
    output            String                    DEFAULT '',
    latency_ms        UInt32                    DEFAULT 0,
    cost_usd          Float32                   DEFAULT 0.0,
    created_at        DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (eval_id, example_id, id)
"""

# ---------------------------------------------------------------------------
# DDL — migrations for existing tables (idempotent)
# ---------------------------------------------------------------------------

_MIGRATIONS = [
    "ALTER TABLE {db}.traces ADD COLUMN IF NOT EXISTS decision Nullable(String)",
    "ALTER TABLE {db}.traces ADD COLUMN IF NOT EXISTS confidence_score Nullable(Float64)",
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS decision Nullable(String)",
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS confidence_score Nullable(Float64)",
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS is_replay Bool DEFAULT false",
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS original_span_id Nullable(String)",
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS replay_note Nullable(String)",
    # Index on parent_span_id for efficient tree reconstruction
    "ALTER TABLE {db}.spans ADD INDEX IF NOT EXISTS idx_parent_span parent_span_id TYPE bloom_filter(0.01) GRANULARITY 4",
    # Phase 3 — workspace isolation columns on traces and spans
    "ALTER TABLE {db}.traces ADD COLUMN IF NOT EXISTS workspace_id String DEFAULT 'default'",
    "ALTER TABLE {db}.traces ADD COLUMN IF NOT EXISTS project_name String DEFAULT ''",
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS workspace_id String DEFAULT 'default'",
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS project_name String DEFAULT ''",
    # Prompt tracking on spans
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS prompt_id Nullable(String)",
    "ALTER TABLE {db}.spans ADD INDEX IF NOT EXISTS idx_prompt_id prompt_id TYPE bloom_filter(0.01) GRANULARITY 4",
    # Data-flow lineage: upstream span ids whose output was passed as input
    "ALTER TABLE {db}.spans ADD COLUMN IF NOT EXISTS source_span_ids Array(String) DEFAULT []",
]

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

_local = threading.local()


def _get_client(settings: Optional[Settings] = None) -> Client:
    """
    Return a thread-local ClickHouse client, creating one per thread.

    clickhouse-connect does not support concurrent queries on the same
    client/session, so each worker thread in the FastAPI executor pool
    gets its own connection.

    :param settings: Explicit settings override.
    :returns: Connected :class:`clickhouse_connect.driver.client.Client`.
    """
    client = getattr(_local, 'client', None)
    if client is not None:
        return client
    s = settings or get_settings()
    _local.client = clickhouse_connect.get_client(
        host=s.ch_host,
        port=s.ch_port,
        username=s.ch_user,
        password=s.ch_password,
        secure=s.ch_secure,
    )
    return _local.client


def close_client() -> None:
    """
    Close the thread-local ClickHouse client if open.

    :returns: None
    """
    client = getattr(_local, 'client', None)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
        _local.client = None


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def ensure_schema(settings: Optional[Settings] = None) -> None:
    """
    Create the database and tables if they do not exist, then run migrations.

    :param settings: Optional settings override.
    :returns: None
    """
    s = settings or get_settings()
    client = _get_client(s)
    db = s.ch_database
    client.command(_CREATE_DB.format(db=db))
    client.command(_CREATE_TRACES.format(db=db))
    client.command(_CREATE_SPANS.format(db=db))
    client.command(_CREATE_DATASETS.format(db=db))
    client.command(_CREATE_DATASET_EXAMPLES.format(db=db))
    client.command(_CREATE_EVALUATIONS.format(db=db))
    client.command(_CREATE_EVALUATION_RESULTS.format(db=db))
    for migration in _MIGRATIONS:
        try:
            client.command(migration.format(db=db))
        except Exception as exc:
            logger.debug("verdictlens: migration skipped: %s", exc)
    logger.info("verdictlens: ClickHouse schema ensured in database '%s'", db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json(obj: Any) -> str:
    """
    Serialize an arbitrary value to a JSON string, falling back to repr.

    :param obj: Value to serialize.
    :returns: JSON string.
    """
    if obj is None:
        return "null"
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps(str(obj))


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """
    Parse an ISO-8601 timestamp into a timezone-aware datetime.

    :param ts: ISO string or None.
    :returns: datetime or None.
    """
    if not ts:
        return None
    try:
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return datetime.now(timezone.utc)


def _now_utc() -> datetime:
    """
    Return current UTC datetime.

    :returns: datetime.
    """
    return datetime.now(timezone.utc)


def _normalize_status_for_storage(status: str) -> str:
    """
    Normalize status before writing to ClickHouse.

    :param status: Raw status string.
    :returns: Canonical status.
    """
    if status == "ok":
        return "success"
    return status


def _normalize_status_for_read(status: str) -> str:
    """
    Normalize status when reading from ClickHouse (handles legacy "ok").

    :param status: Stored status string.
    :returns: Canonical status.
    """
    if status == "ok":
        return "success"
    return status


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def insert_trace(trace: TraceIn, settings: Optional[Settings] = None) -> None:
    """
    Insert one trace and its spans into ClickHouse.

    :param trace: Validated trace payload.
    :param settings: Optional settings override.
    :returns: None
    """
    s = settings or get_settings()
    client = _get_client(s)
    db = s.ch_database

    start_dt = _parse_iso(trace.start_time) or _now_utc()
    end_dt = _parse_iso(trace.end_time)
    tu = trace.token_usage

    workspace_id = getattr(trace, "workspace_id", None) or "default"
    project_name = getattr(trace, "project_name", None) or ""

    trace_row = [
        trace.trace_id,
        trace.name,
        start_dt,
        end_dt,
        trace.latency_ms,
        _normalize_status_for_storage(trace.status),
        trace.framework,
        trace.model,
        _safe_json(trace.input),
        _safe_json(trace.output),
        trace.decision,
        trace.confidence_score,
        tu.prompt_tokens if tu else None,
        tu.completion_tokens if tu else None,
        tu.total_tokens if tu else None,
        trace.cost_usd,
        _safe_json(trace.error),
        len(trace.spans),
        _safe_json(trace.metadata),
        _now_utc(),
        workspace_id,
        project_name,
    ]

    client.insert(
        f"{db}.traces",
        [trace_row],
        column_names=[
            "trace_id", "name", "start_time", "end_time", "latency_ms",
            "status", "framework", "model", "input", "output",
            "decision", "confidence_score",
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cost_usd", "error", "span_count", "metadata", "inserted_at",
            "workspace_id", "project_name",
        ],
    )

    if trace.spans:
        _insert_spans(client, db, trace.trace_id, trace.spans, start_dt, workspace_id, project_name)


def _insert_spans(
    client: Client,
    db: str,
    trace_id: str,
    spans: List[SpanIn],
    fallback_start: datetime,
    workspace_id: str = "default",
    project_name: str = "",
) -> None:
    """
    Batch-insert spans for a trace.

    :param client: ClickHouse client.
    :param db: Database name.
    :param trace_id: Parent trace id.
    :param spans: List of span payloads.
    :param fallback_start: Fallback start_time when span has none.
    :param workspace_id: Owning workspace.
    :param project_name: Project name.
    :returns: None
    """
    rows: List[list] = []
    for sp in spans:
        sp_start = _parse_iso(sp.start_time) or fallback_start
        sp_end = _parse_iso(sp.end_time)
        stu = sp.token_usage
        prompt_id = getattr(sp, "prompt_id", None) or (sp.metadata.get("prompt_id") if isinstance(sp.metadata, dict) else None)
        source_ids = list(getattr(sp, "source_span_ids", None) or [])
        rows.append([
            sp.span_id,
            sp.parent_span_id,
            trace_id,
            sp.name,
            sp.span_type,
            sp_start,
            sp_end,
            sp.latency_ms,
            sp.model,
            _safe_json(sp.input),
            _safe_json(sp.output),
            sp.decision,
            sp.confidence_score,
            stu.prompt_tokens if stu else None,
            stu.completion_tokens if stu else None,
            stu.total_tokens if stu else None,
            sp.cost_usd,
            _safe_json(sp.error),
            _safe_json(sp.metadata),
            _now_utc(),
            workspace_id,
            project_name,
            prompt_id,
            source_ids,
        ])
    client.insert(
        f"{db}.spans",
        rows,
        column_names=[
            "span_id", "parent_span_id", "trace_id", "name", "span_type",
            "start_time", "end_time", "latency_ms", "model", "input", "output",
            "decision", "confidence_score",
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cost_usd", "error", "metadata", "inserted_at",
            "workspace_id", "project_name", "prompt_id", "source_span_ids",
        ],
    )


# ---------------------------------------------------------------------------
# Read — list traces
# ---------------------------------------------------------------------------

def _require_workspace(workspace_id: str) -> None:
    """Safety guard — every query function must call this first."""
    if not workspace_id:
        raise ValueError("workspace_id is required — workspace isolation cannot be bypassed")


def list_traces(
    *,
    workspace_id: str,
    project_name: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
    framework: Optional[str] = None,
    name: Optional[str] = None,
    model: Optional[str] = None,
    start_after: Optional[str] = None,
    start_before: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> TraceListResponse:
    """
    Paginated, filterable trace listing ordered by most recent first.

    :param workspace_id: REQUIRED — workspace scope.
    :param project_name: Optional project filter.
    :param page: 1-based page number.
    :param page_size: Rows per page (max 200).
    :param status: Filter by status (success|error|running).
    :param framework: Filter by framework substring.
    :param name: Filter by name substring.
    :param model: Filter by model substring.
    :param start_after: ISO lower bound on start_time.
    :param start_before: ISO upper bound on start_time.
    :param settings: Optional settings override.
    :returns: Paginated :class:`TraceListResponse`.
    """
    _require_workspace(workspace_id)
    s = settings or get_settings()
    client = _get_client(s)
    db = s.ch_database
    page_size = min(max(page_size, 1), 200)
    page = max(page, 1)
    offset = (page - 1) * page_size

    wheres: List[str] = []
    params: Dict[str, Any] = {}

    if status:
        mapped = _normalize_status_for_storage(status)
        wheres.append("status = {p_status:String}")
        params["p_status"] = mapped
    if framework:
        wheres.append("framework ILIKE {p_fw:String}")
        params["p_fw"] = f"%{framework}%"
    if name:
        wheres.append("name ILIKE {p_name:String}")
        params["p_name"] = f"%{name}%"
    if model:
        wheres.append("model ILIKE {p_model:String}")
        params["p_model"] = f"%{model}%"
    if start_after:
        dt = _parse_iso(start_after)
        if dt:
            wheres.append("start_time >= {p_after:DateTime64(3, 'UTC')}")
            params["p_after"] = dt
    if start_before:
        dt = _parse_iso(start_before)
        if dt:
            wheres.append("start_time <= {p_before:DateTime64(3, 'UTC')}")
            params["p_before"] = dt

    where_clause = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    # Single query: window function count() OVER () avoids a separate COUNT round-trip.
    data_sql = (
        f"SELECT trace_id, name, start_time, end_time, latency_ms, status, "
        f"framework, model, cost_usd, error, span_count, "
        f"prompt_tokens, completion_tokens, total_tokens, metadata, "
        f"count() OVER () AS total_count "
        f"FROM {db}.traces{where_clause} "
        f"ORDER BY start_time DESC "
        f"LIMIT {{p_limit:UInt32}} OFFSET {{p_offset:UInt32}}"
    )
    data_sql, params = scoped(data_sql, params, workspace_id, project_name=project_name)
    params["p_limit"] = page_size
    params["p_offset"] = offset

    result = client.query(data_sql, parameters=params)
    traces: List[TraceOut] = []
    total = 0
    for row in result.result_rows:
        if total == 0:
            total = int(row[15])
        meta = _parse_json_field(row[14])
        traces.append(TraceOut(
            trace_id=row[0],
            name=row[1],
            start_time=_fmt_dt(row[2]),
            end_time=_fmt_dt(row[3]),
            latency_ms=row[4],
            status=_normalize_status_for_read(row[5]) if row[5] else "success",
            framework=row[6],
            model=row[7],
            cost_usd=row[8],
            error=_parse_json_field(row[9]),
            span_count=row[10] or 0,
            prompt_tokens=row[11],
            completion_tokens=row[12],
            total_tokens=row[13],
            metadata=meta,
        ))

    return TraceListResponse(traces=traces, total=total, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Read — full-text search across trace name, input, output
# ---------------------------------------------------------------------------

def search_traces(
    query: str,
    workspace_id: str = "default",
    page: int = 1,
    page_size: int = 50,
) -> TraceListResponse:
    """
    Full-text search across trace name, input, and output.

    :param query: Search string (case-insensitive substring match).
    :param workspace_id: REQUIRED — workspace scope.
    :param page: 1-based page number.
    :param page_size: Rows per page (max 200).
    :returns: Paginated :class:`TraceListResponse`.
    """
    _require_workspace(workspace_id)
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database
    page_size = min(max(page_size, 1), 200)
    page = max(page, 1)
    q = query.replace("'", "\\'")
    where = (
        f"workspace_id = '{workspace_id}'"
        f" AND ("
        f"positionCaseInsensitive(name, '{q}') > 0"
        f" OR positionCaseInsensitive(coalesce(input, ''), '{q}') > 0"
        f" OR positionCaseInsensitive(coalesce(output, ''), '{q}') > 0"
        f")"
    )
    count_sql = f"SELECT count() FROM {db}.traces WHERE {where}"
    total = int(client.query(count_sql).first_row[0])
    offset = (page - 1) * page_size
    sql = (
        f"SELECT trace_id, name, start_time, end_time, latency_ms, status, "
        f"framework, model, cost_usd, error, span_count, "
        f"prompt_tokens, completion_tokens, total_tokens, metadata "
        f"FROM {db}.traces "
        f"WHERE {where} "
        f"ORDER BY start_time DESC "
        f"LIMIT {page_size} OFFSET {offset}"
    )
    result = client.query(sql)
    traces: List[TraceOut] = []
    for row in result.result_rows:
        meta = _parse_json_field(row[14])
        traces.append(TraceOut(
            trace_id=row[0],
            name=row[1],
            start_time=_fmt_dt(row[2]),
            end_time=_fmt_dt(row[3]),
            latency_ms=row[4],
            status=_normalize_status_for_read(row[5]) if row[5] else "success",
            framework=row[6],
            model=row[7],
            cost_usd=row[8],
            error=_parse_json_field(row[9]),
            span_count=row[10] or 0,
            prompt_tokens=row[11],
            completion_tokens=row[12],
            total_tokens=row[13],
            metadata=meta,
        ))
    return TraceListResponse(traces=traces, total=total, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Read — trace detail
# ---------------------------------------------------------------------------

def get_trace(
    trace_id: str,
    *,
    workspace_id: str,
    settings: Optional[Settings] = None,
) -> Optional[TraceDetailOut]:
    """
    Fetch a single trace with all of its spans, scoped by workspace.

    :param trace_id: Trace identifier.
    :param workspace_id: REQUIRED — workspace scope.
    :param settings: Optional settings override.
    :returns: :class:`TraceDetailOut` or None if not found.
    """
    _require_workspace(workspace_id)
    s = settings or get_settings()
    client = _get_client(s)
    db = s.ch_database

    trace_sql = (
        f"SELECT trace_id, name, start_time, end_time, latency_ms, status, "
        f"framework, model, input, output, "
        f"decision, confidence_score, "
        f"prompt_tokens, completion_tokens, total_tokens, "
        f"cost_usd, error, metadata "
        f"FROM {db}.traces WHERE trace_id = {{tid:String}} LIMIT 1"
    )
    params: Dict[str, Any] = {"tid": trace_id}
    trace_sql, params = scoped(trace_sql, params, workspace_id)
    result = client.query(trace_sql, parameters=params)
    if not result.result_rows:
        return None

    r = result.result_rows[0]
    tu = None
    if any(r[i] is not None for i in (12, 13, 14)):
        tu = TokenUsageOut(prompt_tokens=r[12], completion_tokens=r[13], total_tokens=r[14])

    spans = get_spans_for_trace(trace_id, workspace_id=workspace_id, settings=s)

    return TraceDetailOut(
        trace_id=r[0],
        name=r[1],
        start_time=_fmt_dt(r[2]),
        end_time=_fmt_dt(r[3]),
        latency_ms=r[4],
        status=_normalize_status_for_read(r[5]) if r[5] else "success",
        framework=r[6],
        model=r[7],
        input=_parse_json_field(r[8]),
        output=_parse_json_field(r[9]),
        decision=r[10],
        confidence_score=r[11],
        token_usage=tu,
        cost_usd=r[15],
        error=_parse_json_field(r[16]),
        spans=spans,
        metadata=_parse_json_field(r[17]),
    )


def get_spans_for_trace(
    trace_id: str,
    *,
    workspace_id: str,
    settings: Optional[Settings] = None,
) -> List[SpanOut]:
    """
    Fetch all spans for a trace, ordered by start_time, scoped by workspace.

    :param trace_id: Trace identifier.
    :param workspace_id: REQUIRED — workspace scope.
    :param settings: Optional settings override.
    :returns: List of :class:`SpanOut`.
    """
    _require_workspace(workspace_id)
    s = settings or get_settings()
    client = _get_client(s)
    db = s.ch_database

    span_sql = (
        f"SELECT span_id, parent_span_id, trace_id, name, span_type, "
        f"start_time, end_time, latency_ms, model, input, output, "
        f"decision, confidence_score, "
        f"prompt_tokens, completion_tokens, total_tokens, "
        f"cost_usd, error, metadata, source_span_ids "
        f"FROM {db}.spans WHERE trace_id = {{tid:String}} "
        f"AND (is_replay = false OR is_replay IS NULL) "
        f"ORDER BY start_time ASC"
    )
    params: Dict[str, Any] = {"tid": trace_id}
    span_sql, params = scoped(span_sql, params, workspace_id)
    span_result = client.query(span_sql, parameters=params)
    spans: List[SpanOut] = []
    for sr in span_result.result_rows:
        stu = None
        if any(sr[i] is not None for i in (13, 14, 15)):
            stu = TokenUsageOut(prompt_tokens=sr[13], completion_tokens=sr[14], total_tokens=sr[15])
        spans.append(SpanOut(
            span_id=sr[0],
            parent_span_id=sr[1],
            trace_id=sr[2],
            name=sr[3],
            span_type=sr[4],
            start_time=_fmt_dt(sr[5]),
            end_time=_fmt_dt(sr[6]),
            latency_ms=sr[7],
            model=sr[8],
            input=_parse_json_field(sr[9]),
            output=_parse_json_field(sr[10]),
            decision=sr[11],
            confidence_score=sr[12],
            token_usage=stu,
            cost_usd=sr[16],
            error=_parse_json_field(sr[17]),
            metadata=_parse_json_field(sr[18]),
            source_span_ids=list(sr[19]) if sr[19] else [],
        ))
    return spans


# ---------------------------------------------------------------------------
# Read — metrics
# ---------------------------------------------------------------------------

def get_metrics(
    *,
    workspace_id: str,
    project_name: Optional[str] = None,
    hours: int = 24,
    settings: Optional[Settings] = None,
) -> MetricsResponse:
    """
    Compute aggregated metrics over the last ``hours`` hours, scoped by workspace.

    :param workspace_id: REQUIRED — workspace scope.
    :param project_name: Optional project filter.
    :param hours: Lookback window.
    :param settings: Optional settings override.
    :returns: :class:`MetricsResponse` with aggregated stats.
    """
    _require_workspace(workspace_id)
    s = settings or get_settings()
    client = _get_client(s)
    db = s.ch_database

    time_filter = f"start_time >= now() - INTERVAL {int(hours)} HOUR"

    agg_sql = (
        f"SELECT "
        f"  count() AS total_traces, "
        f"  sum(span_count) AS total_spans, "
        f"  sumIf(cost_usd, cost_usd IS NOT NULL) AS total_cost, "
        f"  sumIf(total_tokens, total_tokens IS NOT NULL) AS total_tok, "
        f"  avgIf(latency_ms, latency_ms IS NOT NULL) AS avg_lat, "
        f"  countIf(status = 'error') AS err_count "
        f"FROM {db}.traces WHERE {time_filter}"
    )
    agg_params: Dict[str, Any] = {}
    agg_sql, agg_params = scoped(agg_sql, agg_params, workspace_id, project_name=project_name)
    row = client.query(agg_sql, parameters=agg_params).first_row
    total_traces = int(row[0])
    err_count = int(row[5])
    error_rate = round(err_count / total_traces, 4) if total_traces > 0 else 0.0

    by_status = _group_count(client, db, "status", time_filter, workspace_id, project_name)
    by_fw = _group_count(client, db, "framework", time_filter, workspace_id, project_name)
    by_model = _group_count(client, db, "model", time_filter, workspace_id, project_name)

    cost_model_sql = (
        f"SELECT model, sum(cost_usd) AS c "
        f"FROM {db}.traces WHERE {time_filter} AND model IS NOT NULL AND cost_usd IS NOT NULL "
        f"GROUP BY model ORDER BY c DESC LIMIT 20"
    )
    cost_params: Dict[str, Any] = {}
    cost_model_sql, cost_params = scoped(cost_model_sql, cost_params, workspace_id, project_name=project_name)
    cost_by_model: Dict[str, float] = {}
    for cr in client.query(cost_model_sql, parameters=cost_params).result_rows:
        if cr[0]:
            cost_by_model[cr[0]] = round(float(cr[1]), 6)

    hourly_sql = (
        f"SELECT toStartOfHour(start_time) AS h, count() AS c "
        f"FROM {db}.traces WHERE {time_filter} "
        f"GROUP BY h ORDER BY h"
    )
    hourly_params: Dict[str, Any] = {}
    hourly_sql, hourly_params = scoped(hourly_sql, hourly_params, workspace_id, project_name=project_name)
    hourly: List[Dict[str, Any]] = []
    for hr in client.query(hourly_sql, parameters=hourly_params).result_rows:
        hourly.append({"hour": _fmt_dt(hr[0]), "count": int(hr[1])})

    tok_sql = (
        f"SELECT model, sum(prompt_tokens), sum(completion_tokens) "
        f"FROM {db}.traces WHERE {time_filter} AND model IS NOT NULL "
        f"GROUP BY model"
    )
    tok_params: Dict[str, Any] = {}
    tok_sql, tok_params = scoped(tok_sql, tok_params, workspace_id, project_name=project_name)
    token_breakdown: Dict[str, Dict[str, int]] = {}
    for tr in client.query(tok_sql, parameters=tok_params).result_rows:
        if tr[0]:
            token_breakdown[tr[0]] = {
                "prompt": int(tr[1] or 0),
                "completion": int(tr[2] or 0),
            }

    return MetricsResponse(
        total_traces=total_traces,
        total_spans=int(row[1] or 0),
        total_cost_usd=round(float(row[2] or 0), 6),
        total_tokens=int(row[3] or 0),
        avg_latency_ms=round(float(row[4]), 3) if row[4] is not None else None,
        error_rate=error_rate,
        traces_by_status=by_status,
        traces_by_framework=by_fw,
        traces_by_model=by_model,
        cost_by_model=cost_by_model,
        hourly_trace_counts=hourly,
        token_breakdown_by_model=token_breakdown,
    )


def _group_count(
    client: Client,
    db: str,
    col: str,
    time_filter: str,
    workspace_id: str,
    project_name: Optional[str] = None,
) -> Dict[str, int]:
    """
    Group-by count on a column within the time window, scoped by workspace.
    """
    sql = (
        f"SELECT {col}, count() AS c FROM {db}.traces "
        f"WHERE {time_filter} AND {col} IS NOT NULL AND {col} != '' "
        f"GROUP BY {col} ORDER BY c DESC LIMIT 50"
    )
    params: Dict[str, Any] = {}
    sql, params = scoped(sql, params, workspace_id, project_name=project_name)
    out: Dict[str, int] = {}
    for row in client.query(sql, parameters=params).result_rows:
        if row[0]:
            out[str(row[0])] = int(row[1])
    return out


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_dt(val: Any) -> Optional[str]:
    """
    Format a datetime or string into ISO-8601 with Z suffix.

    :param val: datetime, string, or None.
    :returns: Formatted string or None.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return str(val)


def _parse_json_field(val: Any) -> Any:
    """
    Parse a JSON string stored in ClickHouse back to Python objects.

    :param val: Raw string or None.
    :returns: Parsed structure.
    """
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if val == "null":
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val


# ---------------------------------------------------------------------------
# Monitoring — time-series analytics
# ---------------------------------------------------------------------------

def _bucket_fn(hours: int) -> str:
    """Pick a ClickHouse time-bucketing function based on window size."""
    if hours <= 6:
        return "toStartOfFifteenMinutes"
    if hours <= 48:
        return "toStartOfHour"
    return "toStartOfDay"


def monitoring_traces(
    *,
    workspace_id: str,
    hours: int = 168,
    project_name: Optional[str] = None,
) -> MonitoringTraces:
    """Trace count, error rate, and latency percentiles over time."""
    _require_workspace(workspace_id)
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database
    bucket = _bucket_fn(hours)
    tf = f"start_time >= now() - INTERVAL {int(hours)} HOUR"

    sql = (
        f"SELECT {bucket}(start_time) AS ts, "
        f"count() AS total, "
        f"countIf(status = 'error') AS errors, "
        f"quantile(0.5)(latency_ms) AS p50, "
        f"quantile(0.95)(latency_ms) AS p95, "
        f"quantile(0.99)(latency_ms) AS p99 "
        f"FROM {db}.traces WHERE {tf} "
        f"GROUP BY ts ORDER BY ts"
    )
    params: Dict[str, Any] = {}
    sql, params = scoped(sql, params, workspace_id, project_name=project_name)
    rows = client.query(sql, parameters=params).result_rows

    trace_counts, error_counts, error_rate, latency = [], [], [], []
    for r in rows:
        t = _fmt_dt(r[0]) or ""
        total, errs = int(r[1]), int(r[2])
        trace_counts.append(TimeSeriesPoint(ts=t, value=total, label="success", value2=errs))
        error_counts.append(TimeSeriesPoint(ts=t, value=errs))
        error_rate.append(TimeSeriesPoint(ts=t, value=round(errs / total, 4) if total else 0))
        latency.append(LatencyPercentilesPoint(
            ts=t,
            p50=round(float(r[3] or 0), 1),
            p95=round(float(r[4] or 0), 1),
            p99=round(float(r[5] or 0), 1),
        ))

    return MonitoringTraces(
        trace_counts=trace_counts,
        error_counts=error_counts,
        error_rate=error_rate,
        latency_percentiles=latency,
    )


def monitoring_llm(
    *,
    workspace_id: str,
    hours: int = 168,
    project_name: Optional[str] = None,
) -> MonitoringLLM:
    """LLM call count and latency percentiles from spans with span_type='llm'."""
    _require_workspace(workspace_id)
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database
    bucket = _bucket_fn(hours)
    tf = f"start_time >= now() - INTERVAL {int(hours)} HOUR"

    sql = (
        f"SELECT {bucket}(start_time) AS ts, "
        f"count() AS total, "
        f"countIf(error IS NOT NULL AND error != '' AND error != 'null') AS errors, "
        f"quantile(0.5)(latency_ms) AS p50, "
        f"quantile(0.95)(latency_ms) AS p95, "
        f"quantile(0.99)(latency_ms) AS p99 "
        f"FROM {db}.spans WHERE {tf} AND span_type = 'llm' "
        f"AND (is_replay = false OR is_replay IS NULL) "
        f"GROUP BY ts ORDER BY ts"
    )
    params: Dict[str, Any] = {}
    sql, params = scoped(sql, params, workspace_id, project_name=project_name)
    rows = client.query(sql, parameters=params).result_rows

    call_counts, error_counts, latency = [], [], []
    for r in rows:
        t = _fmt_dt(r[0]) or ""
        total, errs = int(r[1]), int(r[2])
        call_counts.append(TimeSeriesPoint(ts=t, value=total, value2=errs))
        error_counts.append(TimeSeriesPoint(ts=t, value=errs))
        latency.append(LatencyPercentilesPoint(
            ts=t,
            p50=round(float(r[3] or 0), 1),
            p95=round(float(r[4] or 0), 1),
            p99=round(float(r[5] or 0), 1),
        ))

    return MonitoringLLM(
        call_counts=call_counts,
        error_counts=error_counts,
        latency_percentiles=latency,
    )


def monitoring_cost_tokens(
    *,
    workspace_id: str,
    hours: int = 168,
    project_name: Optional[str] = None,
) -> MonitoringCostTokens:
    """Cost and token usage time-series from the traces table."""
    _require_workspace(workspace_id)
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database
    bucket = _bucket_fn(hours)
    tf = f"start_time >= now() - INTERVAL {int(hours)} HOUR"

    sql = (
        f"SELECT {bucket}(start_time) AS ts, "
        f"sum(cost_usd) AS total_cost, "
        f"avg(cost_usd) AS avg_cost, "
        f"sum(prompt_tokens) AS in_tok, "
        f"sum(completion_tokens) AS out_tok, "
        f"avg(prompt_tokens) AS avg_in, "
        f"avg(completion_tokens) AS avg_out, "
        f"count() AS cnt "
        f"FROM {db}.traces WHERE {tf} "
        f"GROUP BY ts ORDER BY ts"
    )
    params: Dict[str, Any] = {}
    sql, params = scoped(sql, params, workspace_id, project_name=project_name)
    rows = client.query(sql, parameters=params).result_rows

    total_cost, cost_per, in_tok, out_tok, in_per, out_per = [], [], [], [], [], []
    for r in rows:
        t = _fmt_dt(r[0]) or ""
        total_cost.append(TimeSeriesPoint(ts=t, value=round(float(r[1] or 0), 6)))
        cost_per.append(TimeSeriesPoint(ts=t, value=round(float(r[2] or 0), 6)))
        in_tok.append(TimeSeriesPoint(ts=t, value=int(r[3] or 0)))
        out_tok.append(TimeSeriesPoint(ts=t, value=int(r[4] or 0)))
        in_per.append(TimeSeriesPoint(ts=t, value=round(float(r[5] or 0), 1)))
        out_per.append(TimeSeriesPoint(ts=t, value=round(float(r[6] or 0), 1)))

    return MonitoringCostTokens(
        total_cost=total_cost,
        cost_per_trace=cost_per,
        input_tokens=in_tok,
        output_tokens=out_tok,
        input_tokens_per_trace=in_per,
        output_tokens_per_trace=out_per,
    )


def monitoring_tools(
    *,
    workspace_id: str,
    hours: int = 168,
    project_name: Optional[str] = None,
) -> MonitoringTools:
    """Tool usage metrics from spans with span_type='tool'."""
    _require_workspace(workspace_id)
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database
    bucket = _bucket_fn(hours)
    tf = f"start_time >= now() - INTERVAL {int(hours)} HOUR"

    # Grouped by tool name
    group_sql = (
        f"SELECT name, count() AS cnt, "
        f"countIf(error IS NOT NULL AND error != '' AND error != 'null') AS errs, "
        f"avg(latency_ms) AS avg_lat, "
        f"sum(cost_usd) AS cost, "
        f"sum(total_tokens) AS tok "
        f"FROM {db}.spans WHERE {tf} AND span_type = 'tool' "
        f"AND (is_replay = false OR is_replay IS NULL) "
        f"GROUP BY name ORDER BY cnt DESC LIMIT 30"
    )
    gp: Dict[str, Any] = {}
    group_sql, gp = scoped(group_sql, gp, workspace_id, project_name=project_name)
    grow = client.query(group_sql, parameters=gp).result_rows

    by_tool = []
    for r in grow:
        cnt = int(r[1])
        errs = int(r[2])
        by_tool.append(GroupedCount(
            name=r[0] or "unknown",
            count=cnt,
            error_count=errs,
            avg_latency_ms=round(float(r[3] or 0), 1),
            error_rate=round(errs / cnt, 4) if cnt else 0,
            total_cost_usd=round(float(r[4] or 0), 6),
            total_tokens=int(r[5] or 0),
        ))

    # Time-series count
    ts_sql = (
        f"SELECT {bucket}(start_time) AS ts, count() AS cnt "
        f"FROM {db}.spans WHERE {tf} AND span_type = 'tool' "
        f"AND (is_replay = false OR is_replay IS NULL) "
        f"GROUP BY ts ORDER BY ts"
    )
    tp: Dict[str, Any] = {}
    ts_sql, tp = scoped(ts_sql, tp, workspace_id, project_name=project_name)
    trows = client.query(ts_sql, parameters=tp).result_rows
    tool_counts = [TimeSeriesPoint(ts=_fmt_dt(r[0]) or "", value=int(r[1])) for r in trows]

    return MonitoringTools(by_tool=by_tool, tool_counts=tool_counts)


def monitoring_run_types(
    *,
    workspace_id: str,
    hours: int = 168,
    project_name: Optional[str] = None,
) -> MonitoringRunTypes:
    """Run type breakdown — spans at depth=1 (direct children of root or root spans)."""
    _require_workspace(workspace_id)
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database
    tf = f"start_time >= now() - INTERVAL {int(hours)} HOUR"

    sql = (
        f"SELECT name, count() AS cnt, "
        f"countIf(error IS NOT NULL AND error != '' AND error != 'null') AS errs, "
        f"avg(latency_ms) AS avg_lat, "
        f"sum(cost_usd) AS cost, "
        f"sum(total_tokens) AS tok "
        f"FROM {db}.spans WHERE {tf} "
        f"AND (parent_span_id IS NULL OR parent_span_id = '') "
        f"AND (is_replay = false OR is_replay IS NULL) "
        f"GROUP BY name ORDER BY cnt DESC LIMIT 30"
    )
    params: Dict[str, Any] = {}
    sql, params = scoped(sql, params, workspace_id, project_name=project_name)
    rows = client.query(sql, parameters=params).result_rows

    by_name = []
    for r in rows:
        cnt = int(r[1])
        errs = int(r[2])
        by_name.append(GroupedCount(
            name=r[0] or "unknown",
            count=cnt,
            error_count=errs,
            avg_latency_ms=round(float(r[3] or 0), 1),
            error_rate=round(errs / cnt, 4) if cnt else 0,
            total_cost_usd=round(float(r[4] or 0), 6),
            total_tokens=int(r[5] or 0),
        ))

    return MonitoringRunTypes(by_name=by_name)


# ---------------------------------------------------------------------------
# Workspace scoping helper (Phase 3)
# ---------------------------------------------------------------------------

def scoped(
    sql: str,
    params: Dict[str, Any],
    workspace_id: str,
    *,
    project_name: Optional[str] = None,
    table_alias: str = "",
) -> tuple[str, Dict[str, Any]]:
    """
    Inject workspace (and optional project) filtering into a SELECT query.

    Appends ``workspace_id = {_ws:String}`` (and optionally ``project_name``)
    to the WHERE clause. Works whether the query already has a WHERE or not.

    :param sql: Original SQL query string.
    :param params: Existing query parameters dict (will be copied, not mutated).
    :param workspace_id: Workspace to scope to.
    :param project_name: Optional project filter (ignored if empty/None).
    :param table_alias: Optional table alias prefix (e.g. ``"t."``).
    :returns: Tuple of (modified_sql, merged_params).
    """
    new_params = dict(params)
    prefix = f"{table_alias}." if table_alias and not table_alias.endswith(".") else table_alias

    clauses: List[str] = [f"{prefix}workspace_id = {{_ws:String}}"]
    new_params["_ws"] = workspace_id

    if project_name:
        clauses.append(f"{prefix}project_name = {{_proj:String}}")
        new_params["_proj"] = project_name

    scope_fragment = " AND ".join(clauses)

    sql_upper = sql.upper()
    if " WHERE " in sql_upper:
        idx = sql_upper.index(" WHERE ") + len(" WHERE ")
        modified = sql[:idx] + scope_fragment + " AND " + sql[idx:]
    elif " GROUP BY " in sql_upper:
        idx = sql_upper.index(" GROUP BY ")
        modified = sql[:idx] + " WHERE " + scope_fragment + sql[idx:]
    elif " ORDER BY " in sql_upper:
        idx = sql_upper.index(" ORDER BY ")
        modified = sql[:idx] + " WHERE " + scope_fragment + sql[idx:]
    elif " LIMIT " in sql_upper:
        idx = sql_upper.index(" LIMIT ")
        modified = sql[:idx] + " WHERE " + scope_fragment + sql[idx:]
    else:
        modified = sql + " WHERE " + scope_fragment

    return modified, new_params
