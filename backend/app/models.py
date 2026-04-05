"""
Pydantic request / response models for the VerdictLens API.

Field names and types align with the canonical contract defined in
``sdk/verdictlens/schema.py`` (schema version 2.0.0).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared helpers (mirrors sdk/verdictlens/schema.py without import dependency)
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"ok", "success", "error", "running"}


def _normalize_status(raw: str) -> str:
    """Map legacy ``'ok'`` to ``'success'``; pass through valid values."""
    if raw == "ok":
        return "success"
    return raw if raw in _VALID_STATUSES else "success"


def _normalize_error(raw: object) -> Any:
    """Accept a string, dict, or None and return a canonical error dict."""
    if raw is None:
        return None
    if isinstance(raw, str):
        if not raw:
            return None
        parts = raw.split(": ", 1)
        etype = parts[0] if len(parts) == 2 else "Error"
        emsg = parts[1] if len(parts) == 2 else raw
        return {"type": etype, "message": emsg, "stack": None}
    if isinstance(raw, dict):
        return {
            "type": raw.get("type", "Error"),
            "message": raw.get("message", str(raw)),
            "stack": raw.get("stack"),
        }
    return {"type": "Error", "message": str(raw), "stack": None}


# ---------------------------------------------------------------------------
# Ingest (SDK → Backend)
# ---------------------------------------------------------------------------

class TokenUsageIn(BaseModel):
    """Token counts attached to a span or trace."""

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class SpanIn(BaseModel):
    """A single span within a trace, as sent by the SDK."""

    span_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_span_id: Optional[str] = None
    name: str = "span"
    span_type: Literal["agent", "llm", "tool", "chain", "retrieval", "other"] = "other"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    latency_ms: Optional[float] = None
    model: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    decision: Optional[str] = None
    confidence_score: Optional[float] = None
    token_usage: Optional[TokenUsageIn] = None
    cost_usd: Optional[float] = None
    error: Optional[Any] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_span_ids: List[str] = Field(default_factory=list)

    @field_validator("error", mode="before")
    @classmethod
    def _normalize_error(cls, v: Any) -> Any:
        """Normalize string errors to ``{type, message, stack}`` dicts."""
        return _normalize_error(v)

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> Any:
        if v is None:
            return None
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return None

    @field_validator("metadata", mode="before")
    @classmethod
    def _coerce_metadata(cls, v: Any) -> Dict[str, Any]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {"value": v}


class TraceIn(BaseModel):
    """Full trace envelope received from the SDK via ``POST /traces``."""

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = "agent_run"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    latency_ms: Optional[float] = None
    status: Literal["ok", "success", "error", "running"] = "success"
    framework: Optional[str] = None
    model: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    decision: Optional[str] = None
    confidence_score: Optional[float] = None
    token_usage: Optional[TokenUsageIn] = None
    cost_usd: Optional[float] = None
    error: Optional[Any] = None
    spans: List[SpanIn] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    workspace_id: Optional[str] = None
    project_name: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> str:
        if isinstance(v, str):
            return _normalize_status(v)
        return "success"

    @field_validator("error", mode="before")
    @classmethod
    def _normalize_error(cls, v: Any) -> Any:
        return _normalize_error(v)

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> Any:
        if v is None:
            return None
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return None

    @field_validator("metadata", mode="before")
    @classmethod
    def _coerce_metadata(cls, v: Any) -> Dict[str, Any]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {"value": v}


# ---------------------------------------------------------------------------
# Query (Backend → Frontend)
# ---------------------------------------------------------------------------

class TokenUsageOut(BaseModel):
    """Token usage in API responses."""

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class SpanOut(BaseModel):
    """Span returned in trace detail responses."""

    span_id: str
    parent_span_id: Optional[str] = None
    trace_id: str
    name: str
    span_type: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    latency_ms: Optional[float] = None
    model: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    decision: Optional[str] = None
    confidence_score: Optional[float] = None
    token_usage: Optional[TokenUsageOut] = None
    cost_usd: Optional[float] = None
    error: Optional[Any] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_span_ids: List[str] = Field(default_factory=list)


class TraceOut(BaseModel):
    """Trace summary in list responses."""

    trace_id: str
    name: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    latency_ms: Optional[float] = None
    status: str = "success"
    framework: Optional[str] = None
    model: Optional[str] = None
    cost_usd: Optional[float] = None
    error: Optional[Any] = None
    span_count: int = 0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TraceDetailOut(BaseModel):
    """Full trace detail including all spans."""

    trace_id: str
    name: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    latency_ms: Optional[float] = None
    status: str = "success"
    framework: Optional[str] = None
    model: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    decision: Optional[str] = None
    confidence_score: Optional[float] = None
    token_usage: Optional[TokenUsageOut] = None
    cost_usd: Optional[float] = None
    error: Optional[Any] = None
    spans: List[SpanOut] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TraceListResponse(BaseModel):
    """Paginated list of traces."""

    traces: List[TraceOut]
    total: int
    page: int
    page_size: int


class MetricsResponse(BaseModel):
    """Aggregated metrics snapshot."""

    total_traces: int = 0
    total_spans: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    avg_latency_ms: Optional[float] = None
    error_rate: float = 0.0
    traces_by_status: Dict[str, int] = Field(default_factory=dict)
    traces_by_framework: Dict[str, int] = Field(default_factory=dict)
    traces_by_model: Dict[str, int] = Field(default_factory=dict)
    cost_by_model: Dict[str, float] = Field(default_factory=dict)
    hourly_trace_counts: List[Dict[str, Any]] = Field(default_factory=list)
    token_breakdown_by_model: Dict[str, Dict[str, int]] = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "total_traces": 1420,
                    "total_spans": 5800,
                    "total_cost_usd": 12.45,
                    "error_rate": 0.034,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Blame response (GET /traces/{id}/blame)
# ---------------------------------------------------------------------------

class BlameSpan(BaseModel):
    """A span annotated with blame role and score."""

    span_id: str
    span_name: str
    role: str
    blame_score: float
    reason: str
    caused_by: Optional[str] = None
    failure_mode: Optional[str] = None  # MAST taxonomy category (NeurIPS 2025)


class BlameResponse(BaseModel):
    """Role-based blame analysis result."""

    originators: List[BlameSpan]
    failure_points: List[BlameSpan] = Field(default_factory=list)
    secondary_contributors: List[BlameSpan] = Field(default_factory=list)
    propagation_chain: List[str]
    confidence: str
    human_summary: str
    retry_storm: bool = False
    full_chain: List[SpanOut]


# ---------------------------------------------------------------------------
# Datasets (Phase 1)
# ---------------------------------------------------------------------------

class DatasetIn(BaseModel):
    """Request body for creating a dataset."""

    name: str
    description: str = ""


class DatasetOut(BaseModel):
    """Dataset as returned by the API."""

    id: str
    name: str
    description: str = ""
    workspace_id: str = "default"
    project_name: str = ""
    created_at: Optional[str] = None
    example_count: int = 0


class ExampleIn(BaseModel):
    """Request body for adding a dataset example."""

    inputs: Any = Field(default_factory=dict)
    outputs: Any = Field(default_factory=dict)
    expected: Any = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_trace_id: Optional[str] = None
    source_span_id: Optional[str] = None
    split: str = Field(default="train", description="Dataset split: train, test, or val")


class ExampleOut(BaseModel):
    """Dataset example as returned by the API."""

    id: str
    dataset_id: str
    inputs: Any = None
    outputs: Any = None
    expected: Any = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_trace_id: Optional[str] = None
    source_span_id: Optional[str] = None
    created_at: Optional[str] = None
    split: str = Field(default="train", description="Dataset split: train, test, or val")


class TraceToDatasetIn(BaseModel):
    """Request body for converting a trace/span to a dataset example."""

    dataset_id: str
    span_id: Optional[str] = None
    expected: Any = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Evaluations (Phase 2)
# ---------------------------------------------------------------------------

class ScorerConfig(BaseModel):
    """Configuration for a single scorer."""

    type: Literal["exact_match", "contains", "llm_judge", "custom", "regex", "json_match"] = "exact_match"
    model: Optional[str] = None
    prompt_template: Optional[str] = None
    field: Optional[str] = None
    threshold: float = 0.5


class EvaluationIn(BaseModel):
    """Request body for creating and triggering an evaluation run."""

    name: str
    dataset_id: str
    scorers: List[ScorerConfig] = Field(default_factory=lambda: [ScorerConfig()])
    mode: Literal["replay", "live"] = "replay"


class EvaluationOut(BaseModel):
    """Evaluation run as returned by the API."""

    id: str
    name: str
    dataset_id: str
    workspace_id: str = "default"
    scorer_config: Any = None
    mode: str = "replay"
    status: str = "pending"
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    total: int = 0
    passed: int = 0
    failed: int = 0
    average_score: float = 0.0


class EvalResultOut(BaseModel):
    """A single evaluation result for one example."""

    id: str
    eval_id: str
    example_id: str
    score: float = 0.0
    passed: bool = False
    output: Any = None
    latency_ms: int = 0
    cost_usd: float = 0.0
    created_at: Optional[str] = None


class OnlineEvalRuleIn(BaseModel):
    name: str
    dataset_id: str
    scorers: List[ScorerConfig] = Field(default_factory=list)
    filter_name: Optional[str] = None


class OnlineEvalRuleOut(BaseModel):
    rule_id: str
    name: str
    dataset_id: str
    workspace_id: str
    scorer_config: Any
    filter_name: Optional[str] = None
    enabled: bool = True
    created_at: str
    last_fired: Optional[str] = None


class CompareExampleDiff(BaseModel):
    """Per-example score comparison between two evaluation runs."""

    example_id: str
    score_a: float
    score_b: float
    passed_a: bool
    passed_b: bool
    delta: float = 0.0


class CompareOut(BaseModel):
    """Side-by-side comparison of two evaluation runs."""

    eval_a_id: str
    eval_b_id: str
    eval_a_name: str = ""
    eval_b_name: str = ""
    wins: int = 0
    losses: int = 0
    ties: int = 0
    diffs: List[CompareExampleDiff] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Workspaces & API Keys (Phase 3)
# ---------------------------------------------------------------------------

class WorkspaceIn(BaseModel):
    """Request body for creating a workspace."""

    name: str
    slug: str
    description: str = ""


class WorkspaceOut(BaseModel):
    """Workspace as returned by the API."""

    id: str
    name: str
    slug: str
    description: str = ""
    created_at: Optional[str] = None


class ApiKeyIn(BaseModel):
    """Request body for creating an API key."""

    name: str
    workspace_id: str


class ApiKeyOut(BaseModel):
    """API key as returned by the API (key is only shown once on creation)."""

    id: str
    name: str
    workspace_id: str
    key_prefix: str
    key: Optional[str] = None
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt Playground (Phase 4)
# ---------------------------------------------------------------------------

class PlaygroundRunIn(BaseModel):
    """Request body for executing a prompt in the playground."""

    prompt: str
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 1024
    system_message: Optional[str] = None
    prompt_version_id: Optional[str] = None


class PlaygroundRunOut(BaseModel):
    """Response from a playground execution."""

    output: Optional[str] = None
    error: Optional[str] = None
    model: str = ""
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    trace_id: Optional[str] = None


class PromptVersionIn(BaseModel):
    """Request body for saving a prompt version."""

    name: str
    content: str
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 1024
    parent_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class PromptVersionOut(BaseModel):
    """Prompt version as returned by the API."""

    id: str
    name: str
    content: str
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 1024
    workspace_id: str = "default"
    version_number: int = 1
    parent_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    is_published: bool = False
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt Hub (Phase 5)
# ---------------------------------------------------------------------------

class PromptVersionHistory(BaseModel):
    """Full version history for a named prompt."""

    name: str
    workspace_id: str
    versions: List[PromptVersionOut] = Field(default_factory=list)
    total_versions: int = 0
    latest_version: Optional[PromptVersionOut] = None


class PromptHubEntry(BaseModel):
    """A published prompt as displayed in the Prompt Hub grid."""

    id: str
    name: str
    content: str
    model: str
    temperature: float
    max_tokens: int
    workspace_id: str
    version_number: int
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    total_versions: int = 1
    usage_count: int = 0


class PromptUsageStats(BaseModel):
    """Usage statistics for a prompt (linked via prompt_id on spans)."""

    prompt_name: str
    total_runs: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    last_used: Optional[str] = None


# ---------------------------------------------------------------------------
# Monitoring dashboard (time-series analytics)
# ---------------------------------------------------------------------------

class TimeSeriesPoint(BaseModel):
    """A single data point in a time-series."""
    ts: str
    value: float = 0.0
    value2: Optional[float] = None
    label: Optional[str] = None


class LatencyPercentilesPoint(BaseModel):
    """Latency percentiles at a point in time."""
    ts: str
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0


class GroupedCount(BaseModel):
    """A named group with a count and optional extra metrics."""
    name: str
    count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    total_cost_usd: float = 0.0
    total_tokens: int = 0


class MonitoringTraces(BaseModel):
    """Trace-level monitoring metrics."""
    trace_counts: List[TimeSeriesPoint] = Field(default_factory=list)
    error_counts: List[TimeSeriesPoint] = Field(default_factory=list)
    error_rate: List[TimeSeriesPoint] = Field(default_factory=list)
    latency_percentiles: List[LatencyPercentilesPoint] = Field(default_factory=list)


class MonitoringLLM(BaseModel):
    """LLM call monitoring metrics."""
    call_counts: List[TimeSeriesPoint] = Field(default_factory=list)
    error_counts: List[TimeSeriesPoint] = Field(default_factory=list)
    latency_percentiles: List[LatencyPercentilesPoint] = Field(default_factory=list)


class MonitoringCostTokens(BaseModel):
    """Cost and token monitoring metrics."""
    total_cost: List[TimeSeriesPoint] = Field(default_factory=list)
    cost_per_trace: List[TimeSeriesPoint] = Field(default_factory=list)
    input_tokens: List[TimeSeriesPoint] = Field(default_factory=list)
    output_tokens: List[TimeSeriesPoint] = Field(default_factory=list)
    input_tokens_per_trace: List[TimeSeriesPoint] = Field(default_factory=list)
    output_tokens_per_trace: List[TimeSeriesPoint] = Field(default_factory=list)


class MonitoringTools(BaseModel):
    """Tool usage monitoring metrics."""
    by_tool: List[GroupedCount] = Field(default_factory=list)
    tool_counts: List[TimeSeriesPoint] = Field(default_factory=list)


class MonitoringRunTypes(BaseModel):
    """Run type (span name at depth=1) monitoring metrics."""
    by_name: List[GroupedCount] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Human Annotations
# ---------------------------------------------------------------------------

class AnnotationIn(BaseModel):
    span_id: Optional[str] = None
    thumbs: Optional[str] = None   # 'up' or 'down'
    label: Optional[str] = None
    note: Optional[str] = None

class AnnotationOut(BaseModel):
    id: str
    trace_id: str
    span_id: Optional[str] = None
    workspace_id: str
    thumbs: Optional[str] = None
    label: Optional[str] = None
    note: Optional[str] = None
    created_at: str
