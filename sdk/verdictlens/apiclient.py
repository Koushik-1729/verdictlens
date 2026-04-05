"""
VerdictLens Python API client — higher-level API for dataset/example management.

Usage:
    from verdictlens import VerdictLensAPIClient

    client = VerdictLensAPIClient(base_url="http://localhost:8000")
    ds = client.create_dataset("my-evals", description="Regression test set")
    client.create_example(ds["id"], inputs={"q": "..."}, outputs={"a": "..."}, expected={"a": "..."})
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


class VerdictLensAPIClient:
    """Synchronous client for VerdictLens dataset and evaluation APIs."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        workspace_id: str = "default",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.workspace_id = workspace_id
        self._headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self._headers["X-VerdictLens-Key"] = api_key
        self._headers["X-Workspace-ID"] = workspace_id

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required: pip install httpx") from exc

        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=30) as c:
            resp = c.request(method, url, headers=self._headers, **kwargs)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    # -- Datasets --------------------------------------------------------------

    def create_dataset(self, name: str, description: str = "") -> Dict[str, Any]:
        """Create a new dataset. Returns the dataset dict."""
        return self._request("POST", "/datasets", json={"name": name, "description": description})

    def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """Fetch a dataset by ID."""
        return self._request("GET", f"/datasets/{dataset_id}")

    def list_datasets(self) -> List[Dict[str, Any]]:
        """List all datasets in the workspace."""
        return self._request("GET", "/datasets")

    def delete_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """Delete a dataset and all its examples."""
        return self._request("DELETE", f"/datasets/{dataset_id}")

    # -- Examples --------------------------------------------------------------

    def create_example(
        self,
        dataset_id: str,
        inputs: Any,
        outputs: Any = None,
        expected: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        split: str = "train",
    ) -> Dict[str, Any]:
        """Add a single example to a dataset."""
        return self._request(
            "POST",
            f"/datasets/{dataset_id}/examples",
            json={
                "inputs": inputs,
                "outputs": outputs or {},
                "expected": expected or {},
                "metadata": metadata or {},
                "split": split,
            },
        )

    def create_examples(
        self,
        dataset_id: str,
        examples: List[Dict[str, Any]],
        split: str = "train",
    ) -> Dict[str, Any]:
        """
        Bulk-import a list of example dicts.

        Each dict: {"inputs": ..., "outputs": ..., "expected": ..., "metadata": ...}
        Uses the /import endpoint with JSONL encoding.
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required: pip install httpx") from exc

        jsonl = "\n".join(json.dumps(e) for e in examples)
        url = f"{self.base_url}/datasets/{dataset_id}/import"
        headers = {k: v for k, v in self._headers.items() if k != "Content-Type"}
        with httpx.Client(timeout=60) as c:
            resp = c.post(
                url,
                headers=headers,
                files={"file": ("examples.jsonl", jsonl.encode(), "application/x-ndjson")},
                params={"split": split},
            )
            resp.raise_for_status()
            return resp.json()

    def list_examples(self, dataset_id: str) -> List[Dict[str, Any]]:
        """List all examples in a dataset."""
        return self._request("GET", f"/datasets/{dataset_id}/examples")

    def delete_example(self, dataset_id: str, example_id: str) -> Dict[str, Any]:
        """Delete a single example."""
        return self._request("DELETE", f"/datasets/{dataset_id}/examples/{example_id}")

    # -- Evaluations -----------------------------------------------------------

    def run_evaluation(
        self,
        name: str,
        dataset_id: str,
        scorer: str = "exact_match",
        mode: str = "replay",
        **scorer_kwargs: Any,
    ) -> Dict[str, Any]:
        """Kick off an evaluation run. Returns the evaluation dict."""
        scorer_config: Dict[str, Any] = {"type": scorer}
        scorer_config.update(scorer_kwargs)
        return self._request(
            "POST",
            "/evaluations",
            json={
                "name": name,
                "dataset_id": dataset_id,
                "scorers": [scorer_config],
                "mode": mode,
            },
        )
