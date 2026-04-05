#!/bin/bash
# ClickHouse init script — runs once when the container starts with an empty data dir.
# Creates the verdictlens database and core tables (schema v2.0.0).

set -e

clickhouse-client -n <<'SQL'

CREATE DATABASE IF NOT EXISTS verdictlens;

CREATE TABLE IF NOT EXISTS verdictlens.traces (
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
    metadata          String                    DEFAULT '{}',
    inserted_at       DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (start_time, trace_id)
PARTITION BY toYYYYMM(start_time);

CREATE TABLE IF NOT EXISTS verdictlens.spans (
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
    metadata          String                    DEFAULT '{}',
    inserted_at       DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (trace_id, start_time, span_id)
PARTITION BY toYYYYMM(start_time);

CREATE TABLE IF NOT EXISTS verdictlens.datasets (
    id           String,
    name         String,
    description  String                    DEFAULT '',
    workspace_id String                    DEFAULT 'default',
    project_name String                    DEFAULT '',
    created_at   DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (workspace_id, created_at, id);

CREATE TABLE IF NOT EXISTS verdictlens.dataset_examples (
    id               String,
    dataset_id       String,
    inputs           Nullable(String),
    outputs          Nullable(String),
    expected         Nullable(String),
    metadata         String                    DEFAULT '{}',
    source_trace_id  Nullable(String),
    source_span_id   Nullable(String),
    created_at       DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC'),
    split            String                    DEFAULT 'train'
) ENGINE = MergeTree()
ORDER BY (dataset_id, created_at, id);

CREATE TABLE IF NOT EXISTS verdictlens.evaluations (
    id            String,
    name          String,
    dataset_id    String,
    workspace_id  String                    DEFAULT 'default',
    scorer_config Nullable(String),
    mode          String                    DEFAULT 'replay',
    status        String                    DEFAULT 'pending',
    created_at    DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC'),
    completed_at  Nullable(DateTime64(3, 'UTC'))
) ENGINE = MergeTree()
ORDER BY (workspace_id, created_at, id);

CREATE TABLE IF NOT EXISTS verdictlens.evaluation_results (
    id          String,
    eval_id     String,
    example_id  String,
    score       Float64                   DEFAULT 0.0,
    passed      UInt8                     DEFAULT 0,
    output      Nullable(String),
    latency_ms  Int64                     DEFAULT 0,
    cost_usd    Float64                   DEFAULT 0.0,
    created_at  DateTime64(3, 'UTC')      DEFAULT now64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (eval_id, created_at, id);

SQL

echo "VerdictLens ClickHouse schema v2.0.0 initialized"
