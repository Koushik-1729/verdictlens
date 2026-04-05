"""
verdictlens-ci — Eval CI Gate CLI

Exits 0 if the evaluation passes the score threshold, 1 if it fails.
Designed for use in GitHub Actions, GitLab CI, and any shell pipeline.

Usage:
    verdictlens-ci <eval_id> [options]

    verdictlens-ci abc123 --threshold 0.85
    verdictlens-ci abc123 --threshold 0.9 --endpoint http://verdictlens:8000
    verdictlens-ci abc123 --json   # machine-readable output

Environment variables (override with CLI flags):
    VERDICTLENS_ENDPOINT   API base URL  (default: http://localhost:8000)
    VERDICTLENS_API_KEY    API key       (optional, for auth-enabled deployments)
    VERDICTLENS_WORKSPACE  Workspace ID  (default: default)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict


def _get_ci_result(
    eval_id: str,
    *,
    endpoint: str,
    api_key: str | None,
    workspace: str,
    threshold: float,
) -> Dict[str, Any]:
    try:
        import httpx
    except ImportError as exc:
        raise SystemExit("httpx is required: pip install httpx") from exc

    base = endpoint.rstrip("/")
    headers: Dict[str, str] = {"X-Workspace-ID": workspace}
    if api_key:
        headers["X-VerdictLens-Key"] = api_key

    url = f"{base}/evaluations/{eval_id}/ci"
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=headers, params={"threshold": threshold})

    if resp.status_code == 404:
        raise SystemExit(f"Evaluation '{eval_id}' not found (404). Check the ID and workspace.")
    if resp.status_code == 403:
        raise SystemExit("Authentication failed (403). Set VERDICTLENS_API_KEY.")
    if resp.status_code != 200:
        raise SystemExit(f"API error {resp.status_code}: {resp.text[:200]}")

    return resp.json()  # type: ignore[no-any-return]


def _print_table(data: Dict[str, Any], threshold: float) -> None:
    passed = data.get("passed", False)
    status_icon = "PASS" if passed else "FAIL"
    divider = "─" * 44

    print(f"\n  VerdictLens CI Gate — {status_icon}")
    print(f"  {divider}")
    print(f"  Evaluation : {data.get('name', data['eval_id'])}")
    print(f"  ID         : {data['eval_id']}")
    print(f"  Score      : {data['score']:.4f}  (threshold: {threshold:.2f})")
    print(f"  Total      : {data.get('total', '?')}  "
          f"passed: {data.get('passed_count', '?')}  "
          f"failed: {data.get('failed_count', '?')}")
    print(f"  Status     : {data.get('status', 'unknown')}")
    print(f"  Result     : {'✓ PASS' if passed else '✗ FAIL'}")
    print(f"  {divider}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="verdictlens-ci",
        description="VerdictLens Eval CI Gate — exits 0 on pass, 1 on fail.",
    )
    parser.add_argument("eval_id", help="Evaluation ID to check")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        metavar="FLOAT",
        help="Pass threshold 0–1 (default: 0.8)",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("VERDICTLENS_ENDPOINT", "http://localhost:8000"),
        metavar="URL",
        help="API base URL (env: VERDICTLENS_ENDPOINT)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("VERDICTLENS_API_KEY"),
        metavar="KEY",
        help="API key (env: VERDICTLENS_API_KEY)",
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("VERDICTLENS_WORKSPACE", "default"),
        metavar="ID",
        help="Workspace ID (env: VERDICTLENS_WORKSPACE)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Print raw JSON response and suppress table",
    )

    args = parser.parse_args()

    if not (0.0 <= args.threshold <= 1.0):
        parser.error("--threshold must be between 0.0 and 1.0")

    data = _get_ci_result(
        args.eval_id,
        endpoint=args.endpoint,
        api_key=args.api_key,
        workspace=args.workspace,
        threshold=args.threshold,
    )

    if args.json_output:
        print(json.dumps(data, indent=2))
    else:
        _print_table(data, args.threshold)

    sys.exit(0 if data.get("passed") else 1)


if __name__ == "__main__":
    main()
