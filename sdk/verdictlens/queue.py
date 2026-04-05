"""
Durable on-disk queue for trace payloads when the backend is unavailable.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterator, List, Optional

from verdictlens.serializers import dumps_json


def _default_queue_dir() -> Path:
    """
    Resolve the default queue directory under the user's home folder.

    :returns: Absolute path to the queue directory.
    """
    return Path.home() / ".verdictlens" / "queue"


class DiskQueue:
    """
    Append-only JSONL queue with a coarse total size budget.

    :param directory: Directory to store segment files, or None to disable disk writes.
    :param max_bytes: Approximate maximum total bytes across segment files.
    """

    def __init__(self, directory: Optional[Path], max_bytes: int) -> None:
        """
        Initialize the disk queue.

        :param directory: Target directory or None to disable persistence.
        :param max_bytes: Maximum bytes to retain on disk.
        """
        self._dir = Path(directory) if directory is not None else None
        self._max_bytes = int(max_bytes)
        self._lock = threading.Lock()

    def enabled(self) -> bool:
        """
        Return True when disk persistence is configured.

        :returns: Whether the queue writes to disk.
        """
        return self._dir is not None

    def _ensure_dir(self) -> Path:
        """
        Create the queue directory if needed.

        :returns: Resolved directory path.
        :raises OSError: If the directory cannot be created.
        """
        if self._dir is None:
            raise RuntimeError("DiskQueue directory is not configured")
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    def enqueue(self, payload: Any) -> None:
        """
        Append a JSON-serializable payload as one JSON line.

        :param payload: Trace payload dict.
        :returns: None
        """
        if not self.enabled():
            return
        try:
            line = dumps_json(payload) + "\n"
            data = line.encode("utf-8")
        except Exception:
            return
        with self._lock:
            try:
                directory = self._ensure_dir()
            except Exception:
                return
            self._prune_locked(directory)
            name = f"{int(time.time() * 1000)}-{uuid.uuid4().hex}.jsonl"
            path = directory / name
            try:
                with open(path, "ab") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError:
                return

    def _total_size_locked(self, directory: Path) -> int:
        """
        Compute total byte size of ``*.jsonl`` files in the directory.

        :param directory: Queue directory.
        :returns: Total bytes.
        """
        total = 0
        for child in directory.glob("*.jsonl"):
            try:
                total += child.stat().st_size
            except OSError:
                continue
        return total

    def _prune_locked(self, directory: Path) -> None:
        """
        Delete oldest segment files until under the byte budget.

        :param directory: Queue directory.
        :returns: None
        """
        if self._max_bytes <= 0:
            return
        files = sorted(directory.glob("*.jsonl"), key=lambda p: p.name)
        total = self._total_size_locked(directory)
        for path in files:
            if total <= self._max_bytes:
                break
            try:
                size = path.stat().st_size
            except OSError:
                continue
            try:
                path.unlink(missing_ok=True)
                total -= size
            except OSError:
                continue

    def iter_payloads(self) -> Iterator[Any]:
        """
        Yield parsed payloads from oldest to newest across segment files.

        :yields: Parsed JSON objects.
        """
        if not self.enabled():
            return
        with self._lock:
            try:
                directory = self._ensure_dir()
            except Exception:
                return
            paths = sorted(directory.glob("*.jsonl"), key=lambda p: p.name)
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def clear_file(self, path: Path) -> None:
        """
        Remove a processed segment file.

        :param path: File path.
        :returns: None
        """
        with self._lock:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                return

    def segment_paths(self) -> List[Path]:
        """
        List queue segment files in stable order.

        :returns: List of paths.
        """
        if not self.enabled():
            return []
        with self._lock:
            try:
                directory = self._ensure_dir()
            except Exception:
                return []
            return sorted(directory.glob("*.jsonl"), key=lambda p: p.name)
