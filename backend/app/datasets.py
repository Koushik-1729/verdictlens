"""
Dataset CRUD — create, list, get, delete datasets and examples.

All functions accept ``workspace_id`` as a required parameter.
They never read workspace context from anywhere else.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.clickhouse import _get_client, _safe_json, _parse_json_field, _fmt_dt, _now_utc
from app.models import DatasetOut, ExampleIn, ExampleOut
from app.settings import get_settings

logger = logging.getLogger("verdictlens.datasets")


def _ensure_split_column() -> None:
    """Add split column to dataset_examples if missing (idempotent migration)."""
    try:
        s = get_settings()
        client = _get_client(s)
        db = s.ch_database
        client.command(
            f"ALTER TABLE {db}.dataset_examples ADD COLUMN IF NOT EXISTS split String DEFAULT 'train'"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

def create_dataset(
    *,
    name: str,
    description: str = "",
    workspace_id: str,
    project_name: str = "",
) -> DatasetOut:
    """
    Create a new dataset.

    :param name: Dataset name.
    :param description: Optional description.
    :param workspace_id: Owning workspace.
    :param project_name: Optional project scope.
    :returns: Created dataset.
    """
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    dataset_id = str(uuid4())
    now = _now_utc()

    client.insert(
        f"{db}.datasets",
        [[dataset_id, name, description, workspace_id, project_name, now]],
        column_names=["id", "name", "description", "workspace_id", "project_name", "created_at"],
    )

    return DatasetOut(
        id=dataset_id,
        name=name,
        description=description,
        workspace_id=workspace_id,
        project_name=project_name,
        created_at=_fmt_dt(now),
        example_count=0,
    )


def list_datasets(*, workspace_id: str) -> List[DatasetOut]:
    """
    List all datasets for a workspace, most recent first.

    :param workspace_id: Workspace to scope.
    :returns: List of datasets with example counts.
    """
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    sql = (
        f"SELECT d.id, d.name, d.description, d.workspace_id, d.project_name, "
        f"d.created_at, count(e.id) AS example_count "
        f"FROM {db}.datasets AS d "
        f"LEFT JOIN {db}.dataset_examples AS e ON d.id = e.dataset_id "
        f"WHERE d.workspace_id = {{ws:String}} "
        f"GROUP BY d.id, d.name, d.description, d.workspace_id, d.project_name, d.created_at "
        f"ORDER BY d.created_at DESC"
    )
    result = client.query(sql, parameters={"ws": workspace_id})
    datasets: List[DatasetOut] = []
    for row in result.result_rows:
        datasets.append(DatasetOut(
            id=row[0],
            name=row[1],
            description=row[2],
            workspace_id=row[3],
            project_name=row[4],
            created_at=_fmt_dt(row[5]),
            example_count=int(row[6]),
        ))
    return datasets


def get_dataset(*, dataset_id: str, workspace_id: str) -> Optional[DatasetOut]:
    """
    Fetch a single dataset with its example count.

    :param dataset_id: Dataset identifier.
    :param workspace_id: Workspace to scope.
    :returns: Dataset or None if not found.
    """
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    sql = (
        f"SELECT d.id, d.name, d.description, d.workspace_id, d.project_name, "
        f"d.created_at, count(e.id) AS example_count "
        f"FROM {db}.datasets AS d "
        f"LEFT JOIN {db}.dataset_examples AS e ON d.id = e.dataset_id "
        f"WHERE d.id = {{did:String}} AND d.workspace_id = {{ws:String}} "
        f"GROUP BY d.id, d.name, d.description, d.workspace_id, d.project_name, d.created_at "
        f"LIMIT 1"
    )
    result = client.query(sql, parameters={"did": dataset_id, "ws": workspace_id})
    if not result.result_rows:
        return None

    row = result.result_rows[0]
    return DatasetOut(
        id=row[0],
        name=row[1],
        description=row[2],
        workspace_id=row[3],
        project_name=row[4],
        created_at=_fmt_dt(row[5]),
        example_count=int(row[6]),
    )


def delete_dataset(*, dataset_id: str, workspace_id: str) -> bool:
    """
    Delete a dataset and all its examples.

    :param dataset_id: Dataset identifier.
    :param workspace_id: Workspace to scope.
    :returns: True if the dataset existed.
    """
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    check = client.query(
        f"SELECT count() FROM {db}.datasets "
        f"WHERE id = {{did:String}} AND workspace_id = {{ws:String}}",
        parameters={"did": dataset_id, "ws": workspace_id},
    )
    if not check.result_rows or check.result_rows[0][0] == 0:
        return False

    client.command(
        f"ALTER TABLE {db}.dataset_examples DELETE WHERE dataset_id = {{did:String}}",
        parameters={"did": dataset_id},
    )
    client.command(
        f"ALTER TABLE {db}.datasets DELETE WHERE id = {{did:String}} AND workspace_id = {{ws:String}}",
        parameters={"did": dataset_id, "ws": workspace_id},
    )
    return True


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------

def add_example(
    *,
    dataset_id: str,
    workspace_id: str,
    example: ExampleIn,
) -> ExampleOut:
    """
    Add an example to a dataset.

    :param dataset_id: Target dataset.
    :param workspace_id: Workspace scope (used to verify dataset ownership).
    :param example: Example data.
    :returns: Created example.
    """
    _ensure_split_column()
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    ds_check = client.query(
        f"SELECT count() FROM {db}.datasets "
        f"WHERE id = {{did:String}} AND workspace_id = {{ws:String}}",
        parameters={"did": dataset_id, "ws": workspace_id},
    )
    if not ds_check.result_rows or ds_check.result_rows[0][0] == 0:
        raise ValueError(f"Dataset {dataset_id} not found in workspace {workspace_id}")

    example_id = str(uuid4())
    now = _now_utc()

    client.insert(
        f"{db}.dataset_examples",
        [[
            example_id,
            dataset_id,
            _safe_json(example.inputs),
            _safe_json(example.outputs),
            _safe_json(example.expected),
            _safe_json(example.metadata),
            example.source_trace_id,
            example.source_span_id,
            now,
            example.split,
        ]],
        column_names=[
            "id", "dataset_id", "inputs", "outputs", "expected",
            "metadata", "source_trace_id", "source_span_id", "created_at", "split",
        ],
    )

    return ExampleOut(
        id=example_id,
        dataset_id=dataset_id,
        inputs=example.inputs,
        outputs=example.outputs,
        expected=example.expected,
        metadata=example.metadata,
        source_trace_id=example.source_trace_id,
        source_span_id=example.source_span_id,
        created_at=_fmt_dt(now),
        split=example.split,
    )


def list_examples(*, dataset_id: str, workspace_id: str) -> List[ExampleOut]:
    """
    List all examples in a dataset, most recent first.

    :param dataset_id: Dataset identifier.
    :param workspace_id: Workspace scope (used to verify dataset ownership).
    :returns: List of examples.
    """
    _ensure_split_column()
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    ds_check = client.query(
        f"SELECT count() FROM {db}.datasets "
        f"WHERE id = {{did:String}} AND workspace_id = {{ws:String}}",
        parameters={"did": dataset_id, "ws": workspace_id},
    )
    if not ds_check.result_rows or ds_check.result_rows[0][0] == 0:
        raise ValueError(f"Dataset {dataset_id} not found in workspace {workspace_id}")

    sql = (
        f"SELECT id, dataset_id, inputs, outputs, expected, metadata, "
        f"source_trace_id, source_span_id, created_at, split "
        f"FROM {db}.dataset_examples "
        f"WHERE dataset_id = {{did:String}} "
        f"ORDER BY created_at DESC"
    )
    result = client.query(sql, parameters={"did": dataset_id})
    examples: List[ExampleOut] = []
    for row in result.result_rows:
        examples.append(ExampleOut(
            id=row[0],
            dataset_id=row[1],
            inputs=_parse_json_field(row[2]),
            outputs=_parse_json_field(row[3]),
            expected=_parse_json_field(row[4]),
            metadata=_parse_json_field(row[5]) or {},
            source_trace_id=row[6],
            source_span_id=row[7],
            created_at=_fmt_dt(row[8]),
            split=row[9] if len(row) > 9 and row[9] else "train",
        ))
    return examples


def import_examples_bulk(
    *,
    dataset_id: str,
    workspace_id: str,
    rows: List[Dict[str, Any]],
    split: str = "train",
) -> int:
    """
    Bulk import examples from a list of dicts (parsed from CSV or JSONL).

    Each dict should have keys: inputs, outputs, expected (optional), metadata (optional).
    Returns count of imported examples.
    """
    count = 0
    for row in rows:
        try:
            example = ExampleIn(
                inputs=row.get("inputs", row),
                outputs=row.get("outputs", {}),
                expected=row.get("expected", {}),
                metadata=row.get("metadata", {}),
                split=row.get("split", split),
            )
            add_example(dataset_id=dataset_id, workspace_id=workspace_id, example=example)
            count += 1
        except Exception as exc:
            logger.warning("verdictlens: bulk import row failed: %s", exc)
            continue
    return count


def delete_example(*, dataset_id: str, example_id: str, workspace_id: str) -> bool:
    """
    Delete a single example from a dataset.

    :param dataset_id: Parent dataset.
    :param example_id: Example identifier.
    :param workspace_id: Workspace scope.
    :returns: True if the example existed.
    """
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    ds_check = client.query(
        f"SELECT count() FROM {db}.datasets "
        f"WHERE id = {{did:String}} AND workspace_id = {{ws:String}}",
        parameters={"did": dataset_id, "ws": workspace_id},
    )
    if not ds_check.result_rows or ds_check.result_rows[0][0] == 0:
        raise ValueError(f"Dataset {dataset_id} not found in workspace {workspace_id}")

    check = client.query(
        f"SELECT count() FROM {db}.dataset_examples "
        f"WHERE id = {{eid:String}} AND dataset_id = {{did:String}}",
        parameters={"eid": example_id, "did": dataset_id},
    )
    if not check.result_rows or check.result_rows[0][0] == 0:
        return False

    client.command(
        f"ALTER TABLE {db}.dataset_examples DELETE WHERE id = {{eid:String}} AND dataset_id = {{did:String}}",
        parameters={"eid": example_id, "did": dataset_id},
    )
    return True


# ---------------------------------------------------------------------------
# Trace-to-dataset conversion
# ---------------------------------------------------------------------------

def trace_to_example(
    *,
    trace_id: str,
    dataset_id: str,
    workspace_id: str,
    span_id: Optional[str] = None,
    expected: Any = None,
) -> ExampleOut:
    """
    Convert a trace or specific span into a dataset example.

    If ``span_id`` is provided, uses that span's input/output.
    Otherwise uses the root trace's input/output.

    :param trace_id: Source trace.
    :param dataset_id: Target dataset.
    :param workspace_id: Workspace scope.
    :param span_id: Optional specific span to extract.
    :param expected: Optional expected output.
    :returns: Created example.
    """
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    if span_id:
        sql = (
            f"SELECT input, output, metadata "
            f"FROM {db}.spans "
            f"WHERE span_id = {{sid:String}} AND trace_id = {{tid:String}} "
            f"AND workspace_id = {{ws:String}} "
            f"LIMIT 1"
        )
        result = client.query(sql, parameters={"sid": span_id, "tid": trace_id, "ws": workspace_id})
        source_span_id = span_id
    else:
        sql = (
            f"SELECT input, output, metadata "
            f"FROM {db}.traces "
            f"WHERE trace_id = {{tid:String}} "
            f"AND workspace_id = {{ws:String}} "
            f"LIMIT 1"
        )
        result = client.query(sql, parameters={"tid": trace_id, "ws": workspace_id})
        source_span_id = None

    if not result.result_rows:
        raise ValueError(f"Trace {trace_id}" + (f" / span {span_id}" if span_id else "") + " not found")

    row = result.result_rows[0]
    inputs = _parse_json_field(row[0])
    outputs = _parse_json_field(row[1])
    metadata = _parse_json_field(row[2]) or {}

    return add_example(
        dataset_id=dataset_id,
        workspace_id=workspace_id,
        example=ExampleIn(
            inputs=inputs,
            outputs=outputs,
            expected=expected or {},
            metadata=metadata,
            source_trace_id=trace_id,
            source_span_id=source_span_id,
        ),
    )
