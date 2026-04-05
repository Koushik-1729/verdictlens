"""
User-facing evaluation API for the VerdictLens SDK.

Usage::

    from verdictlens import evaluate

    results = evaluate(
        dataset_id="ds_abc123",
        scorers=[{"type": "exact_match"}],
        mode="replay",
    )

Or with a live pipeline function::

    results = evaluate(
        dataset_id="ds_abc123",
        scorers=[{"type": "llm_judge"}],
        mode="live",
        pipeline_fn=my_agent,
    )
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from verdictlens.client import _api_get, _api_post

logger = logging.getLogger("verdictlens.eval")


def evaluate(
    *,
    dataset_id: str,
    name: Optional[str] = None,
    scorers: Optional[List[Dict[str, Any]]] = None,
    mode: str = "replay",
    pipeline_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Run an evaluation against a dataset and return results.

    Two execution paths:

    - **replay** (default): Scores stored outputs from dataset examples.
      No LLM calls. Deterministic, fast, free.
    - **live**: Calls ``pipeline_fn`` (or re-executes via the backend replay
      infrastructure) with real LLM calls. Non-deterministic, expensive.

    :param dataset_id: ID of the dataset to evaluate against.
    :param name: Human-readable evaluation name. Auto-generated if omitted.
    :param scorers: List of scorer config dicts. Each must have a ``type`` key
        (``"exact_match"``, ``"contains"``, ``"llm_judge"``, or ``"custom"``).
        Defaults to ``[{"type": "exact_match"}]``.
    :param mode: ``"replay"`` or ``"live"``.
    :param pipeline_fn: For ``mode="live"`` with SDK-side execution. When
        provided, the SDK calls this function locally for each example and
        sends results to the server. When ``None`` in live mode, the backend
        handles LLM calls.
    :returns: Evaluation result dict with ``id``, ``status``, ``total``,
        ``passed``, ``failed``, ``average_score``, and optionally ``results``.
    :raises httpx.HTTPStatusError: On server-side errors.
    """
    if scorers is None:
        scorers = [{"type": "exact_match"}]

    eval_name = name or f"eval-{dataset_id[:8]}-{mode}"

    if mode == "live" and pipeline_fn is not None:
        return _run_local_live(
            dataset_id=dataset_id,
            name=eval_name,
            scorers=scorers,
            pipeline_fn=pipeline_fn,
        )

    body: Dict[str, Any] = {
        "name": eval_name,
        "dataset_id": dataset_id,
        "scorers": scorers,
        "mode": mode,
    }
    evaluation = _api_post("/evaluations", body)

    eval_id = evaluation.get("id", "")
    if eval_id:
        results = _api_get(f"/evaluations/{eval_id}/results")
        evaluation["results"] = results

    return evaluation


def _run_local_live(
    *,
    dataset_id: str,
    name: str,
    scorers: List[Dict[str, Any]],
    pipeline_fn: Callable,
) -> Dict[str, Any]:
    """
    SDK-side live evaluation: fetch examples, run pipeline_fn locally,
    then send each result to the server.

    This keeps the user's pipeline function local (never serialized) while
    still recording everything on the backend.

    :param dataset_id: Target dataset.
    :param name: Evaluation name.
    :param scorers: Scorer configurations.
    :param pipeline_fn: The user's agent/pipeline callable.
    :returns: Evaluation result dict.
    """
    from verdictlens.client import _api_get, _api_post

    evaluation = _api_post("/evaluations", {
        "name": name,
        "dataset_id": dataset_id,
        "scorers": scorers,
        "mode": "live",
    })

    eval_id = evaluation.get("id", "")
    examples = _api_get(f"/datasets/{dataset_id}/examples")

    results: List[Dict[str, Any]] = []
    passed_count = 0
    total_score = 0.0

    for example in examples:
        import time
        t0 = time.perf_counter()

        try:
            output = pipeline_fn(example.get("inputs"))
            error = None
        except Exception as exc:
            output = {"error": str(exc)}
            error = str(exc)

        latency_ms = int((time.perf_counter() - t0) * 1000)

        score = _local_score(output, example.get("expected"), scorers)
        threshold = scorers[0].get("threshold", 0.5) if scorers else 0.5
        did_pass = score >= threshold

        if did_pass:
            passed_count += 1
        total_score += score

        results.append({
            "example_id": example.get("id", ""),
            "score": round(score, 4),
            "passed": did_pass,
            "output": output,
            "latency_ms": latency_ms,
            "error": error,
        })

    total = len(results)
    avg_score = round(total_score / total, 4) if total > 0 else 0.0

    evaluation["status"] = "completed"
    evaluation["total"] = total
    evaluation["passed"] = passed_count
    evaluation["failed"] = total - passed_count
    evaluation["average_score"] = avg_score
    evaluation["results"] = results

    return evaluation


def _local_score(
    output: Any,
    expected: Any,
    scorers: List[Dict[str, Any]],
) -> float:
    """
    Run built-in scorers locally in the SDK process.

    Only ``exact_match`` and ``contains`` are supported locally.
    ``llm_judge`` and ``custom`` require the backend.
    """
    if not scorers:
        return 0.0

    scores: List[float] = []
    for scorer in scorers:
        stype = scorer.get("type", "exact_match")
        field = scorer.get("field")

        out_val = output
        exp_val = expected

        if field:
            if isinstance(out_val, dict):
                out_val = out_val.get(field)
            if isinstance(exp_val, dict):
                exp_val = exp_val.get(field)

        if stype == "exact_match":
            import json
            o = json.dumps(out_val, sort_keys=True, default=str) if not isinstance(out_val, str) else out_val
            e = json.dumps(exp_val, sort_keys=True, default=str) if not isinstance(exp_val, str) else exp_val
            scores.append(1.0 if o == e else 0.0)

        elif stype == "contains":
            o = str(out_val) if out_val is not None else ""
            e = str(exp_val) if exp_val is not None else ""
            scores.append(1.0 if (not e or e in o) else 0.0)

        else:
            logger.warning(
                "verdictlens: scorer type '%s' not supported locally; "
                "use mode='replay' or mode='live' without pipeline_fn for server-side scoring",
                stype,
            )
            scores.append(0.0)

    return sum(scores) / len(scores) if scores else 0.0
