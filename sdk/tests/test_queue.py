"""
Tests for the on-disk queue implementation.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from verdictlens.queue import DiskQueue


def test_disk_queue_writes_jsonl() -> None:
    """
    Enqueue should create a JSONL segment under the workspace test directory.

    :returns: None
    """
    root = Path(__file__).resolve().parents[1] / "tmp_test_queues"
    root.mkdir(exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        dq = DiskQueue(directory=directory, max_bytes=10_000_000)
        dq.enqueue({"trace_id": "abc", "name": "unit", "status": "ok"})
        files = list(directory.glob("*.jsonl"))
        assert files
        payload = json.loads(files[0].read_text(encoding="utf-8").strip().splitlines()[0])
        assert payload["trace_id"] == "abc"
    finally:
        for child in directory.glob("*"):
            child.unlink(missing_ok=True)
        directory.rmdir()
