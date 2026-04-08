"""
API route definitions for VerdictLens.

All routes are grouped under an :class:`fastapi.APIRouter` mounted at ``/``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import json
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from app.alerts import AlertRuleIn, AlertRuleOut, create_rule, delete_rule, list_rules
from app.auth import (
    create_api_key as _create_api_key,
    create_workspace as _create_workspace,
    delete_api_key as _delete_api_key,
    is_auth_enabled,
    list_api_keys as _list_api_keys,
    list_workspaces as _list_workspaces,
    optional_auth,
    resolve_workspace,
    verify_key,
)
from app.blame import compute_blame
from app.clickhouse import (
    get_metrics,
    get_spans_for_trace,
    get_trace,
    insert_trace,
    list_traces,
    monitoring_cost_tokens,
    monitoring_llm,
    monitoring_run_types,
    monitoring_tools,
    monitoring_traces,
    search_traces,
)
from app.datasets import (
    add_example,
    create_dataset,
    delete_dataset,
    delete_example,
    get_dataset,
    import_examples_bulk,
    list_datasets,
    list_examples,
    trace_to_example,
)
from app.evaluator import (
    compare_evaluations,
    create_evaluation,
    delete_evaluation,
    get_eval_results,
    get_evaluation,
    list_evaluations,
    run_evaluation_live,
    run_evaluation_replay,
)
from app.playground import (
    delete_prompt_version,
    execute_playground_run,
    get_prompt_version,
    get_prompt_usage_stats,
    get_version_history,
    list_prompt_versions,
    list_published_prompts,
    promote_version,
    publish_prompt,
    save_prompt_version,
    unpublish_prompt,
    validate_run,
)
from app.replay import ReplayRequest, ReplayResult, ReplaySummary, execute_replay, list_replays
from app.live import manager
from app.models import (
    AnnotationIn,
    AnnotationOut,
    ApiKeyIn,
    ApiKeyOut,
    BlameResponse,
    CompareOut,
    DatasetIn,
    DatasetOut,
    EvalResultOut,
    EvaluationIn,
    EvaluationOut,
    ExampleIn,
    ExampleOut,
    MetricsResponse,
    MonitoringCostTokens,
    MonitoringLLM,
    MonitoringRunTypes,
    MonitoringTools,
    MonitoringTraces,
    OnlineEvalRuleIn,
    OnlineEvalRuleOut,
    PlaygroundRunIn,
    PlaygroundRunOut,
    PromptHubEntry,
    PromptUsageStats,
    PromptVersionHistory,
    PromptVersionIn,
    PromptVersionOut,
    TraceDetailOut,
    TraceIn,
    TraceListResponse,
    TraceToDatasetIn,
    WorkspaceIn,
    WorkspaceOut,
)

logger = logging.getLogger("verdictlens.routes")

router = APIRouter()

_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>VerdictLens API</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #080f1e;
      color: #c9d4e8;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }
    .card {
      max-width: 560px;
      width: 100%;
      background: #0e1829;
      border: 1px solid #1e2d4a;
      border-radius: 16px;
      padding: 2.5rem;
    }
    .header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }
    .logo { width: 52px; height: 52px; flex-shrink: 0; }
    .brand { display: flex; flex-direction: column; }
    .brand-name { font-size: 1.4rem; font-weight: 700; color: #e2eaf8; letter-spacing: -0.02em; }
    .brand-tag { font-size: 0.78rem; color: #5b7aa8; margin-top: 2px; }
    .divider { border: none; border-top: 1px solid #1e2d4a; margin: 1.5rem 0; }
    .links { display: grid; gap: 0.6rem; }
    .link-row {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.7rem 1rem;
      background: #0a1220;
      border: 1px solid #1a2840;
      border-radius: 8px;
      text-decoration: none;
      transition: border-color 0.15s;
    }
    .link-row:hover { border-color: #3b6abf; }
    .link-left { display: flex; flex-direction: column; gap: 2px; }
    .link-label { font-size: 0.82rem; font-weight: 600; color: #c9d4e8; }
    .link-desc { font-size: 0.72rem; color: #4a6080; }
    .link-url { font-family: "SF Mono", "Fira Code", monospace; font-size: 0.72rem; color: #3b6abf; }
    .badge {
      display: inline-flex; align-items: center; gap: 0.4rem;
      background: #0d2040; border: 1px solid #1e3a60;
      border-radius: 6px; padding: 0.25rem 0.6rem;
      font-size: 0.72rem; color: #5b8dd9;
    }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: #3bca8a; display: inline-block; }
    .footer { margin-top: 1.5rem; font-size: 0.72rem; color: #2e4060; text-align: center; }
    .footer a { color: #3b6abf; text-decoration: none; }
  </style>
</head>
<body>
<div class="card">
  <div class="header">
    <svg class="logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" fill="none">
      <rect width="120" height="120" rx="24" fill="#0E1E3E"/>
      <line x1="42" y1="60" x2="70" y2="44" stroke="#5B8DD9" stroke-width="2.5" stroke-linecap="round"/>
      <line x1="42" y1="60" x2="70" y2="76" stroke="#5B8DD9" stroke-width="2.5" stroke-linecap="round"/>
      <circle cx="38" cy="60" r="7" fill="#5B8DD9"/>
      <circle cx="74" cy="42" r="7" fill="#5B8DD9"/>
      <circle cx="74" cy="78" r="7" fill="#5B8DD9"/>
      <circle cx="57" cy="60" r="11" fill="#E8603A"/>
      <polyline points="60,52 54,61 59,61 56,68" stroke="#0E1E3E" stroke-width="2"
        stroke-linejoin="round" stroke-linecap="round" fill="none"/>
    </svg>
    <div class="brand">
      <span class="brand-name">VerdictLens</span>
      <span class="brand-tag">AI Agent Observability &middot; v0.1.0</span>
    </div>
    <div class="badge" style="margin-left:auto">
      <span class="dot"></span> running
    </div>
  </div>
  <hr class="divider"/>
  <div class="links">
    <a class="link-row" href="/docs">
      <div class="link-left">
        <span class="link-label">Interactive Docs</span>
        <span class="link-desc">Swagger UI — explore and test all endpoints</span>
      </div>
      <span class="link-url">/docs</span>
    </a>
    <a class="link-row" href="/redoc">
      <div class="link-left">
        <span class="link-label">ReDoc Reference</span>
        <span class="link-desc">Full API reference documentation</span>
      </div>
      <span class="link-url">/redoc</span>
    </a>
    <a class="link-row" href="/health">
      <div class="link-left">
        <span class="link-label">Health Check</span>
        <span class="link-desc">API, ClickHouse, and Redis status</span>
      </div>
      <span class="link-url">/health</span>
    </a>
    <a class="link-row" href="/version">
      <div class="link-left">
        <span class="link-label">Version Info</span>
        <span class="link-desc">API and SDK version numbers</span>
      </div>
      <span class="link-url">/version</span>
    </a>
  </div>
  <p class="footer">
    Open source &middot; Apache 2.0 &middot;
    <a href="https://github.com/verdictlens/verdictlens">GitHub</a>
  </p>
</div>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root() -> HTMLResponse:
    """Branded landing page shown when visiting the API root."""
    return HTMLResponse(content=_LANDING_HTML)


_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(
        os.environ.get(
            "VERDICTLENS_WORKERS",
            str(min(32, (os.cpu_count() or 1) + 4)),
        )
    )
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", tags=["system"])
async def health() -> Dict[str, str]:
    """
    Liveness + dependency health probe.

    Uses fresh TCP connections for each check — never reuses cached clients —
    so stopping a container is immediately reflected in the response.

    :returns: Status dict with keys: status, clickhouse, redis.
    """
    import httpx
    from app.live import manager
    from app.settings import get_settings as _get_settings

    s = _get_settings()

    # ── ClickHouse — hit the built-in /ping endpoint (fresh TCP each time) ──
    ch_status = "unreachable"
    try:
        scheme = "https" if s.ch_secure else "http"
        ping_url = f"{scheme}://{s.ch_host}:{s.ch_port}/ping"
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(ping_url)
            ch_status = "connected" if resp.status_code == 200 else "unreachable"
    except Exception:
        ch_status = "unreachable"

    # ── Redis — ping the live manager's connection ───────────────────────────
    redis_status = "unreachable"
    try:
        if manager._redis is not None:
            await manager._redis.ping()
            redis_status = "connected"
        else:
            redis_status = "unavailable"
    except Exception:
        redis_status = "unreachable"

    overall = "ok" if ch_status == "connected" else "degraded"
    return {"status": overall, "clickhouse": ch_status, "redis": redis_status}


@router.get("/version", tags=["system"])
async def version() -> Dict[str, str]:
    """Return API and SDK version info."""
    return {"api_version": "0.1.0", "sdk_version": "0.2.0"}


# ---------------------------------------------------------------------------
# Trace ingest
# ---------------------------------------------------------------------------

@router.post(
    "/traces",
    status_code=201,
    tags=["traces"],
    dependencies=[Depends(optional_auth)],
)
async def ingest_trace(trace: TraceIn, request: Request, background_tasks: BackgroundTasks) -> Dict[str, str]:
    """
    Receive a trace envelope from the SDK and persist it to ClickHouse.

    Also broadcasts the trace to all live WebSocket subscribers.

    :param trace: Validated trace payload.
    :param request: HTTP request (carries workspace_id from auth).
    :returns: Acknowledgement with trace_id.
    """
    if not trace.workspace_id:
        trace.workspace_id = getattr(request.state, "workspace_id", "default")
    if not trace.project_name:
        trace.project_name = getattr(request.state, "project_name", "")

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(_EXECUTOR, insert_trace, trace)
    except Exception as exc:
        logger.error("verdictlens: failed to insert trace %s: %s", trace.trace_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Trace insert failed") from exc

    try:
        payload = trace.model_dump(mode="json")
        await manager.broadcast_trace(payload)
    except Exception as exc:
        logger.debug("verdictlens: broadcast error: %s", exc)

    # Fire online eval rules in background
    workspace_id = trace.workspace_id or "default"
    background_tasks.add_task(
        _run_online_evals_for_trace,
        trace_id=trace.trace_id,
        trace_name=trace.name,
        workspace_id=workspace_id,
        output=trace.output,
    )

    return {"trace_id": trace.trace_id, "status": "accepted"}


# ---------------------------------------------------------------------------
# Trace query
# ---------------------------------------------------------------------------

@router.get(
    "/traces",
    response_model=TraceListResponse,
    tags=["traces"],
    dependencies=[Depends(optional_auth)],
)
async def list_traces_endpoint(
    request: Request,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=200, description="Page size"),
    status: Optional[str] = Query(None, description="Filter: success or error"),
    framework: Optional[str] = Query(None, description="Filter: framework substring"),
    name: Optional[str] = Query(None, description="Filter: trace name substring"),
    model: Optional[str] = Query(None, description="Filter: model substring"),
    start_after: Optional[str] = Query(None, description="ISO lower bound on start_time"),
    start_before: Optional[str] = Query(None, description="ISO upper bound on start_time"),
) -> TraceListResponse:
    """
    Paginated listing of traces with optional filters, scoped by workspace.
    """
    ws = _ws(request)
    proj = _project(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: list_traces(
                workspace_id=ws,
                project_name=proj,
                page=page,
                page_size=page_size,
                status=status,
                framework=framework,
                name=name,
                model=model,
                start_after=start_after,
                start_before=start_before,
            ),
        )
    except Exception as exc:
        logger.error("verdictlens: list_traces failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc


@router.get(
    "/traces/search",
    response_model=TraceListResponse,
    tags=["traces"],
    dependencies=[Depends(optional_auth)],
)
async def search_traces_route(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    request: Request = None,
) -> TraceListResponse:
    """Full-text search across trace name, input, and output."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, search_traces, q, ws, page, page_size)


@router.get(
    "/traces/{trace_id}",
    response_model=TraceDetailOut,
    tags=["traces"],
    dependencies=[Depends(optional_auth)],
)
async def get_trace_detail(trace_id: str, request: Request) -> TraceDetailOut:
    """
    Fetch full trace detail including all child spans, scoped by workspace.
    """
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _EXECUTOR, lambda: get_trace(trace_id, workspace_id=ws)
        )
    except Exception as exc:
        logger.error("verdictlens: get_trace failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")
    return result


# ---------------------------------------------------------------------------
# Blame analysis
# ---------------------------------------------------------------------------

@router.get(
    "/traces/{trace_id}/blame",
    response_model=BlameResponse,
    tags=["blame"],
    dependencies=[Depends(optional_auth)],
)
async def blame_trace(trace_id: str, request: Request) -> BlameResponse:
    """
    Run blame analysis on an error trace to identify the root-cause span.
    Scoped by workspace.
    """
    ws = _ws(request)
    loop = asyncio.get_running_loop()

    try:
        trace = await loop.run_in_executor(
            _EXECUTOR, lambda: get_trace(trace_id, workspace_id=ws)
        )
    except Exception as exc:
        logger.error("verdictlens: blame get_trace failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc

    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")

    try:
        spans = await loop.run_in_executor(
            _EXECUTOR, lambda: get_spans_for_trace(trace_id, workspace_id=ws)
        )
    except Exception as exc:
        logger.error("verdictlens: blame get_spans failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Span query failed") from exc

    result = compute_blame(spans)
    if result is None:
        raise HTTPException(
            status_code=422,
            detail=f"Trace {trace_id} has no error spans — blame analysis not applicable",
        )

    return result


# ---------------------------------------------------------------------------
# Replay / Time-Travel Debugging
# ---------------------------------------------------------------------------

@router.post(
    "/traces/{trace_id}/spans/{span_id}/replay",
    response_model=ReplayResult,
    status_code=201,
    tags=["replay"],
    dependencies=[Depends(optional_auth)],
)
async def replay_span(trace_id: str, span_id: str, req: ReplayRequest, request: Request) -> ReplayResult:
    """Replay a span by re-executing the LLM call with new input, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _EXECUTOR, lambda: execute_replay(trace_id, span_id, req, workspace_id=ws)
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        if "already a replay" in msg:
            raise HTTPException(status_code=400, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc
    except Exception as exc:
        logger.error("verdictlens: replay failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Replay failed") from exc
    return result


@router.get(
    "/traces/{trace_id}/replays",
    response_model=list[ReplaySummary],
    tags=["replay"],
    dependencies=[Depends(optional_auth)],
)
async def list_trace_replays(trace_id: str, request: Request) -> list[ReplaySummary]:
    """List all replay attempts for a trace, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR, lambda: list_replays(trace_id, workspace_id=ws)
        )
    except Exception as exc:
        logger.error("verdictlens: list_replays failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

@router.post("/traces/{trace_id}/annotations", response_model=AnnotationOut, status_code=201, tags=["annotations"], dependencies=[Depends(optional_auth)])
async def create_annotation(trace_id: str, body: AnnotationIn, request: Request) -> AnnotationOut:
    from uuid import uuid4
    from datetime import datetime, timezone as _tz
    from app.database import get_session, Annotation as _Ann
    ws = _ws(request)
    ann_id = str(uuid4())
    now = datetime.now(_tz.utc).isoformat()
    with get_session() as session:
        session.add(_Ann(
            id=ann_id, trace_id=trace_id, span_id=body.span_id,
            workspace_id=ws, thumbs=body.thumbs, label=body.label,
            note=body.note, created_at=now,
        ))
        session.commit()
    return AnnotationOut(id=ann_id, trace_id=trace_id, span_id=body.span_id,
                         workspace_id=ws, thumbs=body.thumbs, label=body.label,
                         note=body.note, created_at=now)


@router.get("/traces/{trace_id}/annotations", response_model=List[AnnotationOut], tags=["annotations"], dependencies=[Depends(optional_auth)])
async def list_annotations(trace_id: str, request: Request) -> List[AnnotationOut]:
    from app.database import get_session, Annotation as _Ann
    ws = _ws(request)
    with get_session() as session:
        rows = session.query(_Ann).filter_by(trace_id=trace_id, workspace_id=ws).order_by(_Ann.created_at.desc()).all()
        return [AnnotationOut(id=r.id, trace_id=r.trace_id, span_id=r.span_id,
                              workspace_id=r.workspace_id, thumbs=r.thumbs, label=r.label,
                              note=r.note, created_at=r.created_at) for r in rows]


@router.delete("/annotations/{annotation_id}", tags=["annotations"], dependencies=[Depends(optional_auth)])
async def delete_annotation(annotation_id: str, request: Request) -> Dict[str, str]:
    from app.database import get_session, Annotation as _Ann
    ws = _ws(request)
    with get_session() as session:
        count = session.query(_Ann).filter_by(id=annotation_id, workspace_id=ws).delete()
        session.commit()
    if not count:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"deleted": annotation_id}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@router.get("/metrics", response_model=MetricsResponse, tags=["metrics"], dependencies=[Depends(optional_auth)])
async def metrics_endpoint(
    request: Request,
    hours: int = Query(24, ge=1, le=8760, description="Lookback window in hours"),
) -> MetricsResponse:
    """Aggregated metrics over a rolling window, scoped by workspace."""
    ws = _ws(request)
    proj = _project(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR, lambda: get_metrics(workspace_id=ws, project_name=proj, hours=hours)
        )
    except Exception as exc:
        logger.error("verdictlens: get_metrics failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Metrics query failed") from exc


# ---------------------------------------------------------------------------
# Monitoring dashboard (time-series analytics)
# ---------------------------------------------------------------------------

@router.get("/monitoring/traces", response_model=MonitoringTraces, tags=["monitoring"], dependencies=[Depends(optional_auth)])
async def monitoring_traces_endpoint(
    request: Request,
    hours: int = Query(168, ge=1, le=2160, description="Lookback window in hours"),
) -> MonitoringTraces:
    """Trace count, error rate, and latency percentiles over time."""
    ws = _ws(request)
    proj = _project(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR, lambda: monitoring_traces(workspace_id=ws, hours=hours, project_name=proj)
    )


@router.get("/monitoring/llm", response_model=MonitoringLLM, tags=["monitoring"], dependencies=[Depends(optional_auth)])
async def monitoring_llm_endpoint(
    request: Request,
    hours: int = Query(168, ge=1, le=2160, description="Lookback window in hours"),
) -> MonitoringLLM:
    """LLM call count and latency percentiles over time."""
    ws = _ws(request)
    proj = _project(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR, lambda: monitoring_llm(workspace_id=ws, hours=hours, project_name=proj)
    )


@router.get("/monitoring/cost-tokens", response_model=MonitoringCostTokens, tags=["monitoring"], dependencies=[Depends(optional_auth)])
async def monitoring_cost_tokens_endpoint(
    request: Request,
    hours: int = Query(168, ge=1, le=2160, description="Lookback window in hours"),
) -> MonitoringCostTokens:
    """Cost and token usage time-series."""
    ws = _ws(request)
    proj = _project(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR, lambda: monitoring_cost_tokens(workspace_id=ws, hours=hours, project_name=proj)
    )


@router.get("/monitoring/tools", response_model=MonitoringTools, tags=["monitoring"], dependencies=[Depends(optional_auth)])
async def monitoring_tools_endpoint(
    request: Request,
    hours: int = Query(168, ge=1, le=2160, description="Lookback window in hours"),
) -> MonitoringTools:
    """Tool usage metrics."""
    ws = _ws(request)
    proj = _project(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR, lambda: monitoring_tools(workspace_id=ws, hours=hours, project_name=proj)
    )


@router.get("/monitoring/run-types", response_model=MonitoringRunTypes, tags=["monitoring"], dependencies=[Depends(optional_auth)])
async def monitoring_run_types_endpoint(
    request: Request,
    hours: int = Query(168, ge=1, le=2160, description="Lookback window in hours"),
) -> MonitoringRunTypes:
    """Run type breakdown by span name at depth=1."""
    ws = _ws(request)
    proj = _project(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR, lambda: monitoring_run_types(workspace_id=ws, hours=hours, project_name=proj)
    )


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

@router.post("/alerts", response_model=AlertRuleOut, status_code=201, tags=["alerts"], dependencies=[Depends(optional_auth)])
async def create_alert(rule: AlertRuleIn) -> AlertRuleOut:
    """
    Create a new alert rule.

    :param rule: Rule definition.
    :returns: Created rule with id.
    """
    return create_rule(rule)


@router.get("/alerts", response_model=list[AlertRuleOut], tags=["alerts"], dependencies=[Depends(optional_auth)])
async def list_alerts() -> list[AlertRuleOut]:
    """
    List all alert rules.

    :returns: List of alert rules.
    """
    return list_rules()


@router.delete("/alerts/{rule_id}", tags=["alerts"], dependencies=[Depends(optional_auth)])
async def delete_alert(rule_id: str) -> Dict[str, str]:
    """
    Delete an alert rule.

    :param rule_id: Rule identifier.
    :returns: Acknowledgement or 404.
    """
    if not delete_rule(rule_id):
        raise HTTPException(status_code=404, detail=f"Alert rule {rule_id} not found")
    return {"status": "deleted", "rule_id": rule_id}


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

def _ws(request: Request) -> str:
    """Read workspace_id from request.state (set by optional_auth)."""
    return getattr(request.state, "workspace_id", "default")


def _project(request: Request) -> Optional[str]:
    """Read project_name from request header (optional narrower scope)."""
    return request.headers.get("X-VerdictLens-Project") or None


@router.post(
    "/datasets",
    response_model=DatasetOut,
    status_code=201,
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def create_dataset_endpoint(body: DatasetIn, request: Request) -> DatasetOut:
    """Create a new dataset."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: create_dataset(
                name=body.name,
                description=body.description,
                workspace_id=ws,
                project_name="",
            ),
        )
    except Exception as exc:
        logger.error("verdictlens: create_dataset failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create dataset") from exc


@router.get(
    "/datasets",
    response_model=List[DatasetOut],
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def list_datasets_endpoint(request: Request) -> List[DatasetOut]:
    """List all datasets for the current workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: list_datasets(workspace_id=ws),
        )
    except Exception as exc:
        logger.error("verdictlens: list_datasets failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc


@router.get(
    "/datasets/{dataset_id}",
    response_model=DatasetOut,
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def get_dataset_endpoint(dataset_id: str, request: Request) -> DatasetOut:
    """Fetch a single dataset by ID, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _EXECUTOR,
            lambda: get_dataset(dataset_id=dataset_id, workspace_id=ws),
        )
    except Exception as exc:
        logger.error("verdictlens: get_dataset failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    return result


@router.delete(
    "/datasets/{dataset_id}",
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def delete_dataset_endpoint(dataset_id: str, request: Request) -> Dict[str, str]:
    """Delete a dataset and all its examples, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        deleted = await loop.run_in_executor(
            _EXECUTOR,
            lambda: delete_dataset(dataset_id=dataset_id, workspace_id=ws),
        )
    except Exception as exc:
        logger.error("verdictlens: delete_dataset failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Delete failed") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    return {"status": "deleted", "dataset_id": dataset_id}


# ---------------------------------------------------------------------------
# Dataset examples
# ---------------------------------------------------------------------------

@router.post(
    "/datasets/{dataset_id}/examples",
    response_model=ExampleOut,
    status_code=201,
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def add_example_endpoint(
    dataset_id: str,
    body: ExampleIn,
    request: Request,
) -> ExampleOut:
    """Add an example to a dataset, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: add_example(
                dataset_id=dataset_id,
                workspace_id=ws,
                example=body,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("verdictlens: add_example failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add example") from exc


@router.post(
    "/datasets/{dataset_id}/import",
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def import_examples_endpoint(
    dataset_id: str,
    request: Request,
    file: UploadFile = File(...),
    split: str = "train",
) -> Dict[str, Any]:
    """Bulk import examples from CSV or JSONL file."""
    import csv
    import io
    ws = _ws(request)

    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    filename = (file.filename or "").lower()

    rows: List[Dict[str, Any]] = []

    if filename.endswith(".jsonl") or filename.endswith(".ndjson"):
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    elif filename.endswith(".json"):
        try:
            data = json.loads(text)
            rows = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")
    else:
        # Treat as CSV
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            rows.append(dict(row))

    if not rows:
        raise HTTPException(status_code=400, detail="No valid rows found in file")

    loop = asyncio.get_event_loop()
    try:
        count = await loop.run_in_executor(
            _EXECUTOR,
            lambda: import_examples_bulk(
                dataset_id=dataset_id,
                workspace_id=ws,
                rows=rows,
                split=split,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("verdictlens: import failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Import failed") from exc

    return {"imported": count, "total_rows": len(rows)}


@router.get(
    "/datasets/{dataset_id}/examples",
    response_model=List[ExampleOut],
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def list_examples_endpoint(dataset_id: str, request: Request) -> List[ExampleOut]:
    """List all examples in a dataset, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: list_examples(dataset_id=dataset_id, workspace_id=ws),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("verdictlens: list_examples failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc


@router.delete(
    "/datasets/{dataset_id}/examples/{example_id}",
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def delete_example_endpoint(
    dataset_id: str,
    example_id: str,
    request: Request,
) -> Dict[str, str]:
    """Delete a specific example from a dataset, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        deleted = await loop.run_in_executor(
            _EXECUTOR,
            lambda: delete_example(
                dataset_id=dataset_id,
                example_id=example_id,
                workspace_id=ws,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("verdictlens: delete_example failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Delete failed") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Example {example_id} not found")
    return {"status": "deleted", "example_id": example_id}


# ---------------------------------------------------------------------------
# Trace → Dataset conversion
# ---------------------------------------------------------------------------

@router.post(
    "/traces/{trace_id}/to-dataset",
    response_model=ExampleOut,
    status_code=201,
    tags=["datasets"],
    dependencies=[Depends(optional_auth)],
)
async def trace_to_dataset_endpoint(trace_id: str, body: TraceToDatasetIn, request: Request) -> ExampleOut:
    """Convert a trace (or a specific span) into a dataset example."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: trace_to_example(
                trace_id=trace_id,
                dataset_id=body.dataset_id,
                span_id=body.span_id,
                expected=body.expected,
                workspace_id=ws,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("verdictlens: trace_to_example failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Conversion failed") from exc


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------

@router.post(
    "/evaluations",
    response_model=EvaluationOut,
    status_code=201,
    tags=["evaluations"],
    dependencies=[Depends(optional_auth)],
)
async def create_evaluation_endpoint(body: EvaluationIn, request: Request) -> EvaluationOut:
    """
    Create and run an evaluation against a dataset.

    The evaluation runs synchronously in the thread pool for now.
    """
    loop = asyncio.get_running_loop()
    workspace_id = _ws(request)

    try:
        evaluation = await loop.run_in_executor(
            _EXECUTOR,
            lambda: create_evaluation(
                name=body.name,
                dataset_id=body.dataset_id,
                workspace_id=workspace_id,
                scorers=body.scorers,
                mode=body.mode,
            ),
        )
    except Exception as exc:
        logger.error("verdictlens: create_evaluation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create evaluation") from exc

    try:
        examples = await loop.run_in_executor(
            _EXECUTOR,
            lambda: list_examples(dataset_id=body.dataset_id, workspace_id=workspace_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not examples:
        raise HTTPException(
            status_code=422,
            detail=f"Dataset {body.dataset_id} has no examples to evaluate",
        )

    try:
        if body.mode == "replay":
            await loop.run_in_executor(
                _EXECUTOR,
                lambda: run_evaluation_replay(
                    eval_id=evaluation.id,
                    examples=examples,
                    scorers=body.scorers,
                ),
            )
        else:
            await loop.run_in_executor(
                _EXECUTOR,
                lambda: run_evaluation_live(
                    eval_id=evaluation.id,
                    examples=examples,
                    scorers=body.scorers,
                ),
            )
    except Exception as exc:
        logger.error("verdictlens: evaluation run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Evaluation execution failed") from exc

    updated = await loop.run_in_executor(
        _EXECUTOR,
        lambda: get_evaluation(eval_id=evaluation.id, workspace_id=workspace_id),
    )
    return updated or evaluation


@router.get(
    "/evaluations",
    response_model=List[EvaluationOut],
    tags=["evaluations"],
    dependencies=[Depends(optional_auth)],
)
async def list_evaluations_endpoint(request: Request) -> List[EvaluationOut]:
    """List all evaluations for the current workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: list_evaluations(workspace_id=ws),
        )
    except Exception as exc:
        logger.error("verdictlens: list_evaluations failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc


@router.get(
    "/evaluations/compare",
    response_model=CompareOut,
    tags=["evaluations"],
    dependencies=[Depends(optional_auth)],
)
async def compare_evaluations_endpoint(
    request: Request,
    eval_a: str = Query(..., description="First evaluation ID"),
    eval_b: str = Query(..., description="Second evaluation ID"),
) -> CompareOut:
    """Compare two evaluation runs side-by-side, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()

    eval_a_obj = await loop.run_in_executor(
        _EXECUTOR,
        lambda: get_evaluation(eval_id=eval_a, workspace_id=ws),
    )
    eval_b_obj = await loop.run_in_executor(
        _EXECUTOR,
        lambda: get_evaluation(eval_id=eval_b, workspace_id=ws),
    )
    if not eval_a_obj:
        raise HTTPException(status_code=404, detail=f"Evaluation {eval_a} not found")
    if not eval_b_obj:
        raise HTTPException(status_code=404, detail=f"Evaluation {eval_b} not found")

    try:
        raw = await loop.run_in_executor(
            _EXECUTOR,
            lambda: compare_evaluations(eval_a_id=eval_a, eval_b_id=eval_b, workspace_id=ws),
        )
    except Exception as exc:
        logger.error("verdictlens: compare_evaluations failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Compare failed") from exc

    return CompareOut(
        eval_a_id=eval_a,
        eval_b_id=eval_b,
        eval_a_name=eval_a_obj.name,
        eval_b_name=eval_b_obj.name,
        wins=raw["wins"],
        losses=raw["losses"],
        ties=raw["ties"],
        diffs=raw["diffs"],
    )


@router.get(
    "/evaluations/{eval_id}",
    response_model=EvaluationOut,
    tags=["evaluations"],
    dependencies=[Depends(optional_auth)],
)
async def get_evaluation_endpoint(eval_id: str, request: Request) -> EvaluationOut:
    """Fetch a single evaluation with stats, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _EXECUTOR,
            lambda: get_evaluation(eval_id=eval_id, workspace_id=ws),
        )
    except Exception as exc:
        logger.error("verdictlens: get_evaluation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Evaluation {eval_id} not found")
    return result


@router.get(
    "/evaluations/{eval_id}/results",
    response_model=List[EvalResultOut],
    tags=["evaluations"],
    dependencies=[Depends(optional_auth)],
)
async def get_eval_results_endpoint(eval_id: str, request: Request) -> List[EvalResultOut]:
    """Fetch all results for an evaluation, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: get_eval_results(eval_id=eval_id, workspace_id=ws),
        )
    except Exception as exc:
        logger.error("verdictlens: get_eval_results failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query failed") from exc


@router.get(
    "/evaluations/{eval_id}/ci",
    tags=["evaluations"],
    dependencies=[Depends(optional_auth)],
)
async def eval_ci_status(
    eval_id: str,
    request: Request,
    threshold: float = Query(0.8, ge=0.0, le=1.0, description="Pass threshold (0–1)"),
) -> Dict[str, Any]:
    """CI/CD gate — returns pass/fail based on evaluation score vs threshold."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _EXECUTOR,
            lambda: get_evaluation(eval_id=eval_id, workspace_id=ws),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Query failed") from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Evaluation {eval_id} not found")
    passed = result.average_score >= threshold
    return {
        "eval_id": eval_id,
        "name": result.name,
        "score": round(result.average_score, 4),
        "threshold": threshold,
        "passed": passed,
        "total": result.total,
        "passed_count": result.passed,
        "failed_count": result.failed,
        "status": result.status,
        "exit_code": 0 if passed else 1,
    }


@router.delete(
    "/evaluations/{eval_id}",
    tags=["evaluations"],
    dependencies=[Depends(optional_auth)],
)
async def delete_evaluation_endpoint(eval_id: str, request: Request) -> Dict[str, str]:
    """Delete an evaluation and all its results, scoped by workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    try:
        deleted = await loop.run_in_executor(
            _EXECUTOR,
            lambda: delete_evaluation(eval_id=eval_id, workspace_id=ws),
        )
    except Exception as exc:
        logger.error("verdictlens: delete_evaluation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Delete failed") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Evaluation {eval_id} not found")
    return {"status": "deleted", "eval_id": eval_id}


# ---------------------------------------------------------------------------
# Online Eval Rules
# ---------------------------------------------------------------------------

def _run_online_evals_for_trace(
    *,
    trace_id: str,
    trace_name: str,
    workspace_id: str,
    output: Any,
) -> None:
    """Fire online eval rules that match this trace. Called as background task."""
    from datetime import datetime, timezone as _tz
    from app.database import get_session, OnlineEvalRule as _OERule
    from app.datasets import list_examples
    from app.evaluator import _run_scorer, _insert_eval_result, create_evaluation
    from app.models import ScorerConfig

    try:
        with get_session() as session:
            rules = session.query(_OERule).filter_by(workspace_id=workspace_id, enabled=True).all()

        for rule in rules:
            if rule.filter_name and rule.filter_name not in trace_name:
                continue

            try:
                scorers = [ScorerConfig(**s) for s in json.loads(rule.scorer_config or "[]")]
                if not scorers:
                    continue

                examples = list_examples(dataset_id=rule.dataset_id, workspace_id=workspace_id)
                if not examples:
                    continue

                # Score the trace output against the first example as reference
                ref_example = examples[0]
                score = sum(_run_scorer(output, ref_example.expected, sc) for sc in scorers) / len(scorers)

                # Store as an eval result under an auto-created evaluation
                eval_out = create_evaluation(
                    name=f"online:{rule.name}:{trace_id[:8]}",
                    dataset_id=rule.dataset_id,
                    workspace_id=workspace_id,
                    scorers=scorers,
                    mode="online",
                )
                _insert_eval_result(
                    eval_id=eval_out.id,
                    example_id=ref_example.id,
                    score=round(score, 4),
                    passed=score >= (scorers[0].threshold or 0.5),
                    output=output,
                    latency_ms=0,
                    cost_usd=0.0,
                )

                # Update last_fired
                with get_session() as session:
                    r = session.query(_OERule).filter_by(rule_id=rule.rule_id).first()
                    if r:
                        r.last_fired = datetime.now(_tz.utc).isoformat()
                        session.commit()

            except Exception as exc:
                logger.warning("verdictlens: online eval rule %s failed: %s", rule.rule_id, exc)

    except Exception as exc:
        logger.warning("verdictlens: _run_online_evals_for_trace error: %s", exc)


@router.post("/online-evals", tags=["evaluations"], dependencies=[Depends(optional_auth)])
async def create_online_eval_rule(body: OnlineEvalRuleIn, request: Request) -> OnlineEvalRuleOut:
    """Create an online eval rule — auto-scores new traces against a dataset."""
    from uuid import uuid4 as _uuid4
    from datetime import datetime, timezone as _tz
    from app.database import get_session, OnlineEvalRule as _OERule

    ws = _ws(request)
    rule_id = str(_uuid4())
    now_str = datetime.now(_tz.utc).isoformat()

    with get_session() as session:
        rule = _OERule(
            rule_id=rule_id,
            name=body.name,
            dataset_id=body.dataset_id,
            workspace_id=ws,
            scorer_config=json.dumps([s.model_dump() for s in body.scorers]),
            filter_name=body.filter_name,
            enabled=True,
            created_at=now_str,
        )
        session.add(rule)
        session.commit()

    return OnlineEvalRuleOut(
        rule_id=rule_id,
        name=body.name,
        dataset_id=body.dataset_id,
        workspace_id=ws,
        scorer_config=[s.model_dump() for s in body.scorers],
        filter_name=body.filter_name,
        enabled=True,
        created_at=now_str,
    )


@router.get("/online-evals", tags=["evaluations"], dependencies=[Depends(optional_auth)])
async def list_online_eval_rules(request: Request) -> List[OnlineEvalRuleOut]:
    """List all online eval rules for this workspace."""
    from app.database import get_session, OnlineEvalRule as _OERule

    ws = _ws(request)
    with get_session() as session:
        rules = session.query(_OERule).filter_by(workspace_id=ws).all()
        return [
            OnlineEvalRuleOut(
                rule_id=r.rule_id,
                name=r.name,
                dataset_id=r.dataset_id,
                workspace_id=r.workspace_id,
                scorer_config=json.loads(r.scorer_config) if r.scorer_config else [],
                filter_name=r.filter_name,
                enabled=bool(r.enabled),
                created_at=r.created_at,
                last_fired=r.last_fired,
            )
            for r in rules
        ]


@router.delete("/online-evals/{rule_id}", tags=["evaluations"], dependencies=[Depends(optional_auth)])
async def delete_online_eval_rule(rule_id: str, request: Request) -> Dict[str, str]:
    """Delete an online eval rule."""
    from app.database import get_session, OnlineEvalRule as _OERule

    ws = _ws(request)
    with get_session() as session:
        rule = session.query(_OERule).filter_by(rule_id=rule_id, workspace_id=ws).first()
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        session.delete(rule)
        session.commit()
    return {"status": "deleted", "rule_id": rule_id}


# ---------------------------------------------------------------------------
# Prompt Playground (Phase 4)
# ---------------------------------------------------------------------------

@router.post(
    "/playground/run",
    response_model=PlaygroundRunOut,
    tags=["playground"],
    dependencies=[Depends(optional_auth)],
)
async def playground_run_endpoint(body: PlaygroundRunIn, request: Request) -> PlaygroundRunOut:
    """Execute a prompt in the playground with safety checks."""
    from app.settings import get_settings as _gs
    settings = _gs()
    ws = _ws(request)
    rate_key = f"playground:{ws}"

    error_msg = validate_run(body, settings, rate_key)
    if error_msg:
        raise HTTPException(status_code=400, detail=error_msg)

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _EXECUTOR,
            lambda: execute_playground_run(body, ws),
        )
    except Exception as exc:
        logger.error("verdictlens: playground run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Playground execution failed") from exc


@router.post(
    "/playground/prompts",
    response_model=PromptVersionOut,
    status_code=201,
    tags=["playground"],
    dependencies=[Depends(optional_auth)],
)
async def save_prompt_endpoint(body: PromptVersionIn, request: Request) -> PromptVersionOut:
    """Save a prompt version."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR,
        lambda: save_prompt_version(body, ws),
    )


@router.get(
    "/playground/prompts",
    response_model=List[PromptVersionOut],
    tags=["playground"],
    dependencies=[Depends(optional_auth)],
)
async def list_prompts_endpoint(request: Request) -> List[PromptVersionOut]:
    """List all saved prompt versions for the workspace."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR,
        lambda: list_prompt_versions(ws),
    )


@router.get(
    "/playground/prompts/{version_id}",
    response_model=PromptVersionOut,
    tags=["playground"],
    dependencies=[Depends(optional_auth)],
)
async def get_prompt_endpoint(version_id: str, request: Request) -> PromptVersionOut:
    """Fetch a single prompt version."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _EXECUTOR,
        lambda: get_prompt_version(version_id, ws),
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Prompt version {version_id} not found")
    return result


@router.delete(
    "/playground/prompts/{version_id}",
    tags=["playground"],
    dependencies=[Depends(optional_auth)],
)
async def delete_prompt_endpoint(version_id: str, request: Request) -> Dict[str, str]:
    """Delete a prompt version."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    deleted = await loop.run_in_executor(
        _EXECUTOR,
        lambda: delete_prompt_version(version_id, ws),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Prompt version {version_id} not found")
    return {"status": "deleted", "version_id": version_id}


# ---------------------------------------------------------------------------
# Prompt Hub (Phase 5)
# ---------------------------------------------------------------------------

@router.get(
    "/playground/prompts/{name}/history",
    response_model=PromptVersionHistory,
    tags=["prompt-hub"],
    dependencies=[Depends(optional_auth)],
)
async def prompt_version_history_endpoint(name: str, request: Request) -> PromptVersionHistory:
    """Get full version history for a named prompt."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR,
        lambda: get_version_history(name, ws),
    )


@router.post(
    "/playground/prompts/{version_id}/publish",
    tags=["prompt-hub"],
    dependencies=[Depends(optional_auth)],
)
async def publish_prompt_endpoint(version_id: str, request: Request) -> Dict[str, str]:
    """Publish a prompt version to the Prompt Hub."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(
        _EXECUTOR,
        lambda: publish_prompt(version_id, ws),
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Prompt version {version_id} not found")
    return {"status": "published", "version_id": version_id}


@router.post(
    "/playground/prompts/{version_id}/unpublish",
    tags=["prompt-hub"],
    dependencies=[Depends(optional_auth)],
)
async def unpublish_prompt_endpoint(version_id: str, request: Request) -> Dict[str, str]:
    """Unpublish a prompt version."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(
        _EXECUTOR,
        lambda: unpublish_prompt(version_id, ws),
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Prompt version {version_id} not found")
    return {"status": "unpublished", "version_id": version_id}


@router.post(
    "/playground/prompts/{version_id}/promote",
    response_model=PromptVersionOut,
    tags=["prompt-hub"],
    dependencies=[Depends(optional_auth)],
)
async def promote_prompt_endpoint(version_id: str, request: Request) -> PromptVersionOut:
    """Promote an older version — creates a new latest version with the same content."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _EXECUTOR,
        lambda: promote_version(version_id, ws),
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Prompt version {version_id} not found")
    return result


@router.get(
    "/prompt-hub",
    response_model=List[PromptHubEntry],
    tags=["prompt-hub"],
    dependencies=[Depends(optional_auth)],
)
async def list_hub_prompts_endpoint(request: Request) -> List[PromptHubEntry]:
    """List all published prompts in the Prompt Hub."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR,
        lambda: list_published_prompts(ws),
    )


@router.get(
    "/prompt-hub/{prompt_name}/pull",
    tags=["prompt-hub"],
    dependencies=[Depends(optional_auth)],
)
async def pull_prompt_endpoint(
    prompt_name: str,
    request: Request,
    version: Optional[int] = Query(None, description="Specific version number; omit for latest"),
) -> Dict[str, Any]:
    """Pull a prompt by name for use in SDK. Returns content + metadata."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    history = await loop.run_in_executor(
        _EXECUTOR,
        lambda: get_version_history(prompt_name, ws),
    )
    if not history or not history.versions:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_name}' not found")
    if version is not None:
        pv = next((v for v in history.versions if v.version_number == version), None)
        if pv is None:
            raise HTTPException(status_code=404, detail=f"Version {version} not found for prompt '{prompt_name}'")
    else:
        pv = history.latest_version or history.versions[0]
    return {
        "name": pv.name,
        "content": pv.content,
        "model": pv.model,
        "temperature": pv.temperature,
        "max_tokens": pv.max_tokens,
        "version_number": pv.version_number,
        "tags": pv.tags,
    }


@router.get(
    "/prompt-hub/{prompt_name}/usage",
    response_model=PromptUsageStats,
    tags=["prompt-hub"],
    dependencies=[Depends(optional_auth)],
)
async def prompt_usage_stats_endpoint(prompt_name: str, request: Request) -> PromptUsageStats:
    """Get usage statistics for a named prompt."""
    ws = _ws(request)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _EXECUTOR,
        lambda: get_prompt_usage_stats(prompt_name, ws),
    )


# ---------------------------------------------------------------------------
# Workspaces & API Keys (Phase 3)
# ---------------------------------------------------------------------------

@router.get(
    "/workspaces",
    response_model=List[WorkspaceOut],
    tags=["workspaces"],
    dependencies=[Depends(optional_auth)],
)
async def list_workspaces_endpoint() -> List[WorkspaceOut]:
    """List all workspaces."""
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(_EXECUTOR, _list_workspaces)
    return [WorkspaceOut(**r) for r in rows]


@router.post(
    "/workspaces",
    response_model=WorkspaceOut,
    status_code=201,
    tags=["workspaces"],
    dependencies=[Depends(optional_auth)],
)
async def create_workspace_endpoint(body: WorkspaceIn) -> WorkspaceOut:
    """Create a new workspace."""
    import hashlib
    from datetime import datetime, timezone
    from uuid import uuid4

    ws_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            _EXECUTOR,
            lambda: _create_workspace(
                workspace_id=ws_id,
                name=body.name,
                slug=body.slug,
                description=body.description,
                created_at=now,
            ),
        )
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail=f"Workspace slug '{body.slug}' already exists") from exc
        logger.error("verdictlens: create_workspace failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create workspace") from exc

    return WorkspaceOut(id=ws_id, name=body.name, slug=body.slug, description=body.description, created_at=now)


@router.post(
    "/workspaces/{workspace_id}/api-keys",
    response_model=ApiKeyOut,
    status_code=201,
    tags=["workspaces"],
    dependencies=[Depends(optional_auth)],
)
async def create_api_key_endpoint(workspace_id: str, body: ApiKeyIn) -> ApiKeyOut:
    """Create a new API key for a workspace. The full key is only returned once."""
    import hashlib
    import secrets
    from datetime import datetime, timezone
    from uuid import uuid4

    raw_key = f"vdl_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key_prefix = raw_key[:10] + "..."
    key_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            _EXECUTOR,
            lambda: _create_api_key(
                key_id=key_id,
                name=body.name,
                workspace_id=workspace_id,
                key_hash=key_hash,
                key_prefix=key_prefix,
                created_at=now,
            ),
        )
    except Exception as exc:
        logger.error("verdictlens: create_api_key failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create API key") from exc

    return ApiKeyOut(
        id=key_id,
        name=body.name,
        workspace_id=workspace_id,
        key_prefix=key_prefix,
        key=raw_key,
        created_at=now,
    )


@router.get(
    "/workspaces/{workspace_id}/api-keys",
    response_model=List[ApiKeyOut],
    tags=["workspaces"],
    dependencies=[Depends(optional_auth)],
)
async def list_api_keys_endpoint(workspace_id: str) -> List[ApiKeyOut]:
    """List API keys for a workspace (without full key values)."""
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(_EXECUTOR, lambda: _list_api_keys(workspace_id))
    return [ApiKeyOut(**r) for r in rows]


@router.delete(
    "/workspaces/{workspace_id}/api-keys/{key_id}",
    tags=["workspaces"],
    dependencies=[Depends(optional_auth)],
)
async def delete_api_key_endpoint(workspace_id: str, key_id: str) -> Dict[str, str]:
    """Delete an API key."""
    loop = asyncio.get_running_loop()
    deleted = await loop.run_in_executor(_EXECUTOR, lambda: _delete_api_key(key_id, workspace_id))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")
    return {"status": "deleted", "key_id": key_id}


# ---------------------------------------------------------------------------
# WebSocket live feed
# ---------------------------------------------------------------------------

@router.websocket("/live")
async def live_feed(
    ws: WebSocket,
    key: Optional[str] = Query(None),
) -> None:
    """
    Stream incoming traces in real-time to connected WebSocket clients.

    When API key auth is enabled, the client must pass ``?key=<api_key>``
    as a query parameter (FastAPI dependencies don't work on WebSocket routes).

    :param ws: WebSocket connection.
    :param key: Optional API key query parameter.
    :returns: None (runs until disconnect).
    """
    if is_auth_enabled():
        if not key or not verify_key(key):
            await ws.close(code=4401)
            return

    await manager.connect(ws)
    try:
        while True:
            _ = await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(ws)

from fastapi import APIRouter
router = APIRouter()

@router.get("/health")
def health_check():
    return {"status": "ok"}