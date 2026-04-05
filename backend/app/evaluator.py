"""
Evaluation engine — run scorers against dataset examples.

Two completely separate execution paths controlled by ``mode``:

- **replay** — uses stored outputs from dataset_examples. No LLM calls.
  Deterministic, fast, free. Runs scorers against stored outputs only.
- **live** — calls ``pipeline_fn`` under @trace so execution is automatically
  captured. Real LLM call. Non-deterministic, expensive. Only used when the
  user explicitly requests it.

These are two separate functions, not one function with a branch.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from app.clickhouse import _get_client, _safe_json, _parse_json_field, _fmt_dt, _now_utc
from app.models import (
    EvalResultOut,
    EvaluationOut,
    ExampleOut,
    ScorerConfig,
)
from app.settings import get_settings

logger = logging.getLogger("verdictlens.evaluator")


# ---------------------------------------------------------------------------
# ClickHouse helpers for evaluations
# ---------------------------------------------------------------------------

def create_evaluation(
    *,
    name: str,
    dataset_id: str,
    workspace_id: str,
    scorers: List[ScorerConfig],
    mode: str = "replay",
) -> EvaluationOut:
    """
    Create an evaluation record in ClickHouse with status=pending.

    :param name: Evaluation name.
    :param dataset_id: Target dataset.
    :param workspace_id: Owning workspace.
    :param scorers: Scorer configurations.
    :param mode: "replay" or "live".
    :returns: Created evaluation.
    """
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    eval_id = str(uuid4())
    now = _now_utc()
    scorer_json = json.dumps([sc.model_dump() for sc in scorers], default=str)

    client.insert(
        f"{db}.evaluations",
        [[eval_id, name, dataset_id, workspace_id, scorer_json, mode, "pending", now, None]],
        column_names=[
            "id", "name", "dataset_id", "workspace_id", "scorer_config",
            "mode", "status", "created_at", "completed_at",
        ],
    )

    return EvaluationOut(
        id=eval_id,
        name=name,
        dataset_id=dataset_id,
        workspace_id=workspace_id,
        scorer_config=json.loads(scorer_json),
        mode=mode,
        status="pending",
        created_at=_fmt_dt(now),
    )


def _update_eval_status(eval_id: str, status: str, completed_at: Optional[datetime] = None) -> None:
    """Update evaluation status (and optionally completed_at) in ClickHouse."""
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    if completed_at:
        client.command(
            f"ALTER TABLE {db}.evaluations UPDATE "
            f"status = '{status}', completed_at = '{completed_at.isoformat()}' "
            f"WHERE id = '{eval_id}'"
        )
    else:
        client.command(
            f"ALTER TABLE {db}.evaluations UPDATE status = '{status}' WHERE id = '{eval_id}'"
        )


def _insert_eval_result(
    *,
    eval_id: str,
    example_id: str,
    score: float,
    passed: bool,
    output: Any,
    latency_ms: int,
    cost_usd: float,
) -> str:
    """Insert a single evaluation result row."""
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    result_id = str(uuid4())
    now = _now_utc()

    client.insert(
        f"{db}.evaluation_results",
        [[result_id, eval_id, example_id, float(score), int(passed), _safe_json(output), int(latency_ms), float(cost_usd), now]],
        column_names=["id", "eval_id", "example_id", "score", "passed", "output", "latency_ms", "cost_usd", "created_at"],
    )
    return result_id


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def list_evaluations(*, workspace_id: str) -> List[EvaluationOut]:
    """List all evaluations for a workspace, most recent first."""
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    sql = (
        f"SELECT id, name, dataset_id, workspace_id, scorer_config, mode, status, "
        f"created_at, completed_at "
        f"FROM {db}.evaluations "
        f"WHERE workspace_id = {{ws:String}} "
        f"ORDER BY created_at DESC"
    )
    result = client.query(sql, parameters={"ws": workspace_id})
    evals: List[EvaluationOut] = []
    for row in result.result_rows:
        stats = _get_eval_stats(row[0])
        evals.append(EvaluationOut(
            id=row[0],
            name=row[1],
            dataset_id=row[2],
            workspace_id=row[3],
            scorer_config=_parse_json_field(row[4]),
            mode=row[5],
            status=row[6],
            created_at=_fmt_dt(row[7]),
            completed_at=_fmt_dt(row[8]),
            **stats,
        ))
    return evals


def get_evaluation(*, eval_id: str, workspace_id: str) -> Optional[EvaluationOut]:
    """Fetch a single evaluation with aggregate stats."""
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    sql = (
        f"SELECT id, name, dataset_id, workspace_id, scorer_config, mode, status, "
        f"created_at, completed_at "
        f"FROM {db}.evaluations "
        f"WHERE id = {{eid:String}} AND workspace_id = {{ws:String}} "
        f"LIMIT 1"
    )
    result = client.query(sql, parameters={"eid": eval_id, "ws": workspace_id})
    if not result.result_rows:
        return None

    row = result.result_rows[0]
    stats = _get_eval_stats(row[0])
    return EvaluationOut(
        id=row[0],
        name=row[1],
        dataset_id=row[2],
        workspace_id=row[3],
        scorer_config=_parse_json_field(row[4]),
        mode=row[5],
        status=row[6],
        created_at=_fmt_dt(row[7]),
        completed_at=_fmt_dt(row[8]),
        **stats,
    )


def _get_eval_stats(eval_id: str) -> Dict[str, Any]:
    """Compute total/passed/failed/average_score for an evaluation."""
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    sql = (
        f"SELECT count() AS total, "
        f"countIf(passed = 1) AS passed_count, "
        f"avg(score) AS avg_score "
        f"FROM {db}.evaluation_results "
        f"WHERE eval_id = {{eid:String}}"
    )
    result = client.query(sql, parameters={"eid": eval_id})
    if not result.result_rows or result.result_rows[0][0] == 0:
        return {"total": 0, "passed": 0, "failed": 0, "average_score": 0.0}

    row = result.result_rows[0]
    total = int(row[0])
    passed = int(row[1])
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "average_score": round(float(row[2] or 0), 4),
    }


def get_eval_results(*, eval_id: str, workspace_id: str) -> List[EvalResultOut]:
    """
    Fetch all results for an evaluation.

    Verifies that the evaluation belongs to the given workspace before
    returning results — prevents cross-workspace data access via eval_id.
    """
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    ownership_check = client.query(
        f"SELECT count() FROM {db}.evaluations "
        f"WHERE id = {{eid:String}} AND workspace_id = {{ws:String}}",
        parameters={"eid": eval_id, "ws": workspace_id},
    )
    if not ownership_check.result_rows or ownership_check.result_rows[0][0] == 0:
        return []

    sql = (
        f"SELECT id, eval_id, example_id, score, passed, output, latency_ms, cost_usd, created_at "
        f"FROM {db}.evaluation_results "
        f"WHERE eval_id = {{eid:String}} "
        f"ORDER BY created_at ASC"
    )
    result = client.query(sql, parameters={"eid": eval_id})
    results: List[EvalResultOut] = []
    for row in result.result_rows:
        results.append(EvalResultOut(
            id=row[0],
            eval_id=row[1],
            example_id=row[2],
            score=float(row[3]),
            passed=bool(row[4]),
            output=_parse_json_field(row[5]),
            latency_ms=int(row[6]),
            cost_usd=float(row[7]),
            created_at=_fmt_dt(row[8]),
        ))
    return results


def delete_evaluation(*, eval_id: str, workspace_id: str) -> bool:
    """Delete an evaluation and all its results."""
    s = get_settings()
    client = _get_client(s)
    db = s.ch_database

    check = client.query(
        f"SELECT count() FROM {db}.evaluations "
        f"WHERE id = {{eid:String}} AND workspace_id = {{ws:String}}",
        parameters={"eid": eval_id, "ws": workspace_id},
    )
    if not check.result_rows or check.result_rows[0][0] == 0:
        return False

    client.command(f"ALTER TABLE {db}.evaluation_results DELETE WHERE eval_id = '{eval_id}'")
    client.command(
        f"ALTER TABLE {db}.evaluations DELETE "
        f"WHERE id = '{eval_id}' AND workspace_id = '{workspace_id}'"
    )
    return True


def compare_evaluations(*, eval_a_id: str, eval_b_id: str, workspace_id: str) -> Dict[str, Any]:
    """
    Compare two evaluation runs side-by-side.

    Both evaluations must belong to the same workspace.

    Returns per-example score diffs and win/loss/tie counts.
    """
    results_a = {r.example_id: r for r in get_eval_results(eval_id=eval_a_id, workspace_id=workspace_id)}
    results_b = {r.example_id: r for r in get_eval_results(eval_id=eval_b_id, workspace_id=workspace_id)}

    all_example_ids = sorted(set(results_a.keys()) | set(results_b.keys()))
    diffs: List[Dict[str, Any]] = []
    wins = losses = ties = 0

    for eid in all_example_ids:
        ra = results_a.get(eid)
        rb = results_b.get(eid)
        score_a = ra.score if ra else 0.0
        score_b = rb.score if rb else 0.0
        passed_a = ra.passed if ra else False
        passed_b = rb.passed if rb else False
        delta = round(score_b - score_a, 4)

        if delta > 0.001:
            wins += 1
        elif delta < -0.001:
            losses += 1
        else:
            ties += 1

        diffs.append({
            "example_id": eid,
            "score_a": score_a,
            "score_b": score_b,
            "passed_a": passed_a,
            "passed_b": passed_b,
            "delta": delta,
        })

    return {
        "eval_a_id": eval_a_id,
        "eval_b_id": eval_b_id,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "diffs": diffs,
    }


# ---------------------------------------------------------------------------
# Built-in scorers
# ---------------------------------------------------------------------------

def _score_exact_match(output: Any, expected: Any, config: ScorerConfig) -> float:
    """1.0 if output equals expected, 0.0 otherwise."""
    field = config.field
    if field:
        if isinstance(output, dict):
            output = output.get(field)
        if isinstance(expected, dict):
            expected = expected.get(field)

    out_str = json.dumps(output, sort_keys=True, default=str) if not isinstance(output, str) else output
    exp_str = json.dumps(expected, sort_keys=True, default=str) if not isinstance(expected, str) else expected
    return 1.0 if out_str == exp_str else 0.0


def _score_contains(output: Any, expected: Any, config: ScorerConfig) -> float:
    """1.0 if expected substring is found in output, 0.0 otherwise."""
    field = config.field
    if field:
        if isinstance(output, dict):
            output = output.get(field, "")
        if isinstance(expected, dict):
            expected = expected.get(field, "")

    out_str = str(output) if output is not None else ""
    exp_str = str(expected) if expected is not None else ""

    if not exp_str:
        return 1.0
    return 1.0 if exp_str in out_str else 0.0


def _score_regex(output: Any, expected: Any, config: ScorerConfig) -> float:
    """1.0 if output matches the regex pattern stored in config.field (used as pattern)."""
    import re
    field = config.field
    if field and isinstance(output, dict):
        output = output.get(field, "")
    pattern = str(expected) if expected is not None else (config.field or "")
    out_str = str(output) if output is not None else ""
    try:
        return 1.0 if re.search(pattern, out_str) else 0.0
    except re.error:
        return 0.0


def _score_json_match(output: Any, expected: Any, config: ScorerConfig) -> float:
    """Score by comparing a specific JSON field path (dot-notation) between output and expected."""
    field = config.field  # e.g. "result.score"
    if not field:
        return _score_exact_match(output, expected, config)

    def _get(obj: Any, path: str) -> Any:
        for key in path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return None
        return obj

    out_val = _get(output, field)
    exp_val = _get(expected, field)
    out_str = json.dumps(out_val, sort_keys=True, default=str) if not isinstance(out_val, str) else out_val
    exp_str = json.dumps(exp_val, sort_keys=True, default=str) if not isinstance(exp_val, str) else exp_val
    return 1.0 if out_str == exp_str else 0.0


def _score_llm_judge(output: Any, expected: Any, config: ScorerConfig) -> float:
    """
    Use an LLM to judge output quality. Imports provider routing from replay.py.

    Returns a score between 0.0 and 1.0.
    """
    from app.replay import _execute_llm_call

    model = config.model or "gpt-4o-mini"
    template = config.prompt_template or (
        "You are an evaluation judge. Score the following output on a scale of 0 to 10.\n\n"
        "Expected output:\n{expected}\n\n"
        "Actual output:\n{output}\n\n"
        "Respond with ONLY a number from 0 to 10."
    )

    prompt_text = template.format(
        output=json.dumps(output, default=str) if not isinstance(output, str) else output,
        expected=json.dumps(expected, default=str) if not isinstance(expected, str) else expected,
    )

    messages_input = {"messages": [{"role": "user", "content": prompt_text}]}

    try:
        result_output, error, latency_ms, cost, total_tokens, token_detail = _execute_llm_call(
            model=model,
            original_input=None,
            new_input=messages_input,
        )
        if error:
            logger.warning("verdictlens: llm_judge call failed: %s", error)
            return 0.0

        content = result_output
        if isinstance(result_output, dict):
            content = result_output.get("content", "")

        raw = str(content).strip()
        for token in raw.split():
            try:
                score = float(token)
                return max(0.0, min(1.0, score / 10.0))
            except ValueError:
                continue
        return 0.0

    except Exception as exc:
        logger.warning("verdictlens: llm_judge scorer error: %s", exc)
        return 0.0


def _run_scorer(output: Any, expected: Any, config: ScorerConfig) -> float:
    """Dispatch to the correct scorer implementation."""
    if config.type == "exact_match":
        return _score_exact_match(output, expected, config)
    elif config.type == "contains":
        return _score_contains(output, expected, config)
    elif config.type == "llm_judge":
        return _score_llm_judge(output, expected, config)
    elif config.type == "regex":
        return _score_regex(output, expected, config)
    elif config.type == "json_match":
        return _score_json_match(output, expected, config)
    elif config.type == "custom":
        logger.warning("verdictlens: custom scorers must be provided via SDK evaluate(). Returning 0.")
        return 0.0
    else:
        logger.warning("verdictlens: unknown scorer type '%s'", config.type)
        return 0.0


# ---------------------------------------------------------------------------
# Execution — replay mode (no LLM calls)
# ---------------------------------------------------------------------------

def run_evaluation_replay(
    *,
    eval_id: str,
    examples: List[ExampleOut],
    scorers: List[ScorerConfig],
) -> None:
    """
    Run an evaluation in replay mode — scores stored outputs only.

    No LLM calls. Deterministic, fast, free.

    :param eval_id: Evaluation identifier.
    :param examples: Dataset examples with stored outputs.
    :param scorers: Scorer configurations.
    """
    _update_eval_status(eval_id, "running")

    try:
        for example in examples:
            t0 = time.perf_counter()

            scores: List[float] = []
            for scorer in scorers:
                score = _run_scorer(example.outputs, example.expected, scorer)
                scores.append(score)

            avg_score = sum(scores) / len(scores) if scores else 0.0
            latency_ms = int((time.perf_counter() - t0) * 1000)

            threshold = scorers[0].threshold if scorers else 0.5
            passed = avg_score >= threshold

            _insert_eval_result(
                eval_id=eval_id,
                example_id=example.id,
                score=round(avg_score, 4),
                passed=passed,
                output=example.outputs,
                latency_ms=latency_ms,
                cost_usd=0.0,
            )

        _update_eval_status(eval_id, "completed", completed_at=_now_utc())

    except Exception as exc:
        logger.error("verdictlens: replay evaluation %s failed: %s", eval_id, exc, exc_info=True)
        _update_eval_status(eval_id, "failed")
        raise


# ---------------------------------------------------------------------------
# Execution — live mode (real LLM calls)
# ---------------------------------------------------------------------------

def run_evaluation_live(
    *,
    eval_id: str,
    examples: List[ExampleOut],
    scorers: List[ScorerConfig],
    pipeline_fn: Optional[Callable] = None,
) -> None:
    """
    Run an evaluation in live mode — executes real LLM calls.

    When ``pipeline_fn`` is provided (SDK path), calls it with example inputs.
    When ``pipeline_fn`` is None (API path), re-executes via the replay LLM call
    infrastructure, treating example inputs as LLM messages.

    Non-deterministic, expensive. Only used when user explicitly requests it.

    :param eval_id: Evaluation identifier.
    :param examples: Dataset examples.
    :param scorers: Scorer configurations.
    :param pipeline_fn: Optional callable — the user's agent/pipeline function.
    """
    from app.replay import _execute_llm_call

    _update_eval_status(eval_id, "running")

    try:
        for example in examples:
            t0 = time.perf_counter()
            cost_usd = 0.0

            if pipeline_fn is not None:
                try:
                    live_output = pipeline_fn(example.inputs)
                except Exception as exc:
                    live_output = {"error": str(exc)}
                latency_ms = int((time.perf_counter() - t0) * 1000)
            else:
                messages_input = _example_to_messages(example.inputs)
                model = _infer_model(example)

                try:
                    live_output, error, lat, cost_usd, _, _ = _execute_llm_call(
                        model=model,
                        original_input=None,
                        new_input=messages_input,
                    )
                    latency_ms = int(lat)
                    if error:
                        live_output = error
                except Exception as exc:
                    live_output = {"error": str(exc)}
                    latency_ms = int((time.perf_counter() - t0) * 1000)

            scores: List[float] = []
            for scorer in scorers:
                score = _run_scorer(live_output, example.expected, scorer)
                scores.append(score)

            avg_score = sum(scores) / len(scores) if scores else 0.0
            threshold = scorers[0].threshold if scorers else 0.5
            passed = avg_score >= threshold

            _insert_eval_result(
                eval_id=eval_id,
                example_id=example.id,
                score=round(avg_score, 4),
                passed=passed,
                output=live_output,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )

        _update_eval_status(eval_id, "completed", completed_at=_now_utc())

    except Exception as exc:
        logger.error("verdictlens: live evaluation %s failed: %s", eval_id, exc, exc_info=True)
        _update_eval_status(eval_id, "failed")
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _example_to_messages(inputs: Any) -> Dict[str, Any]:
    """Convert example inputs into a messages dict for _execute_llm_call."""
    if isinstance(inputs, dict) and "messages" in inputs:
        return inputs

    if isinstance(inputs, str):
        return {"messages": [{"role": "user", "content": inputs}]}

    content = json.dumps(inputs, default=str) if not isinstance(inputs, str) else inputs
    return {"messages": [{"role": "user", "content": content}]}


def _infer_model(example: ExampleOut) -> str:
    """Try to infer a model name from example metadata, fall back to gpt-4o-mini."""
    if isinstance(example.metadata, dict):
        model = example.metadata.get("model")
        if model:
            return str(model)
    return "gpt-4o-mini"
