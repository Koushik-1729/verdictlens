"""
Non-blocking HTTP transport with offline disk queue and background flushing.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from verdictlens.config import get_config
from verdictlens.queue import DiskQueue, _default_queue_dir
from verdictlens.serializers import dumps_json

logger = logging.getLogger("verdictlens")

_CLIENT_LOCK = threading.Lock()
_CLIENT: Optional["VerdictLensClient"] = None


class VerdictLensClient:
    """
    Thread-safe client that enqueues trace payloads and sends them asynchronously.

    :param config: Optional explicit config; defaults to :func:`verdictlens.config.get_config`.
    """

    def __init__(self, config: Optional[Any] = None) -> None:
        """
        Construct a client and start background workers.

        :param config: :class:`~verdictlens.config.VerdictLensConfig` override.
        """
        from verdictlens.config import VerdictLensConfig, get_config as _get_config

        self._config: VerdictLensConfig = config or _get_config()
        self._disk = self._make_disk_queue(self._config)
        self._queue: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(maxsize=50_000)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, name="verdictlens-transport", daemon=True)
        self._thread.start()
        self._flush_thread = threading.Thread(target=self._flush_disk_loop, name="verdictlens-flush", daemon=True)
        self._flush_thread.start()
        atexit.register(self.close)

    @staticmethod
    def _make_disk_queue(cfg: Any) -> DiskQueue:
        """
        Build a :class:`DiskQueue` from configuration (disabled => no disk writes).

        :param cfg: Active :class:`~verdictlens.config.VerdictLensConfig`.
        :returns: Configured disk queue instance.
        """
        if cfg.disabled:
            return DiskQueue(directory=None, max_bytes=0)
        if cfg.queue_dir:
            return DiskQueue(directory=Path(cfg.queue_dir), max_bytes=cfg.max_queue_bytes)
        return DiskQueue(directory=_default_queue_dir(), max_bytes=cfg.max_queue_bytes)

    def send_trace(self, payload: Dict[str, Any]) -> None:
        """
        Enqueue a trace payload for best-effort delivery.

        :param payload: Serialized trace dictionary.
        :returns: None
        """
        cfg = get_config()
        if cfg.disabled:
            return
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            logger.warning("verdictlens: in-memory queue full; writing trace to disk queue")
            self._disk.enqueue(payload)

    def flush(self, timeout: float = 5.0) -> None:
        """
        Block until the in-memory queue drains and the worker finishes processing.

        :param timeout: Seconds to wait for the worker to finish pending items.
        :returns: None
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._queue.empty():
                time.sleep(0.05)
                if self._queue.empty():
                    return
            time.sleep(0.01)

    def close(self) -> None:
        """
        Stop background workers and wait briefly for shutdown.

        :returns: None
        """
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=2.0)
        self._flush_thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        """
        Background thread: dequeue payloads and POST them asynchronously.

        :returns: None
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_worker(loop))
        except Exception as exc:
            logger.exception("verdictlens: transport loop crashed: %s", exc)
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()

    async def _async_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Async worker that drains the thread queue and performs HTTP posts.

        :param loop: The running event loop.
        :returns: None
        """
        async with httpx.AsyncClient(timeout=get_config().timeout_seconds) as client:
            while not self._stop.is_set():
                try:
                    item = await loop.run_in_executor(
                        None,
                        lambda: self._queue.get(block=True, timeout=0.25),
                    )
                except queue.Empty:
                    continue
                except Exception:
                    continue
                if item is None:
                    break
                if get_config().disabled:
                    continue
                await self._post_with_retries(client, item)
                self._maybe_otel_export(item)

    async def _post_with_retries(self, client: httpx.AsyncClient, payload: Dict[str, Any]) -> None:
        """
        POST a payload with bounded retries; fall back to disk on failure.

        :param client: Shared async HTTP client.
        :param payload: Trace JSON dict.
        :returns: None
        """
        cfg = get_config()
        url = cfg.traces_endpoint()
        headers = self._build_headers(cfg)
        body = dumps_json(payload)
        delays = (0.05, 0.2, 0.75)
        for attempt, delay in enumerate((*delays, None), start=1):
            try:
                response = await client.post(url, content=body, headers=headers)
                if response.status_code < 500:
                    if response.status_code >= 400:
                        logger.warning(
                            "verdictlens: ingest rejected (%s): %s",
                            response.status_code,
                            response.text[:512],
                        )
                    return
            except Exception as exc:
                logger.debug("verdictlens: ingest attempt %s failed: %s", attempt, exc, exc_info=True)
            if delay is None:
                break
            await asyncio.sleep(delay)
        self._disk.enqueue(payload)

    def _maybe_otel_export(self, payload: Dict[str, Any]) -> None:
        """
        If OTel export is enabled, translate the payload into OTel spans (best-effort).

        :param payload: Trace JSON dict.
        :returns: None
        """
        try:
            cfg = get_config()
            if not cfg.otel_export:
                return
            from verdictlens.otel_export import export_trace_as_otel
            export_trace_as_otel(payload)
        except Exception as exc:
            logger.debug("verdictlens: OTel export error: %s", exc)

    def _build_headers(self, cfg: Any) -> Dict[str, str]:
        """
        Build HTTP headers for ingest requests.

        :param cfg: Active configuration.
        :returns: Header mapping.
        """
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["X-VerdictLens-Key"] = cfg.api_key
        if cfg.workspace:
            headers["X-VerdictLens-Workspace"] = cfg.workspace
        if cfg.project:
            headers["X-VerdictLens-Project"] = cfg.project
        headers.update(dict(cfg.extra_headers))
        return headers

    def _flush_disk_loop(self) -> None:
        """
        Periodically attempt to flush on-disk queued payloads.

        :returns: None
        """
        while not self._stop.is_set():
            if get_config().disabled:
                time.sleep(1.0)
                continue
            try:
                self._flush_disk_once()
            except Exception as exc:
                logger.debug("verdictlens: disk flush error: %s", exc, exc_info=True)
            time.sleep(2.0)

    def _flush_disk_once(self) -> None:
        """
        Read one segment file and try to POST each line.

        :returns: None
        """
        if not self._disk.enabled():
            return
        paths = self._disk.segment_paths()
        if not paths:
            return
        path = paths[0]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            self._disk.clear_file(path)
            return

        payloads: list[Dict[str, Any]] = []
        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                payloads.append(obj)

        cfg = get_config()
        if cfg.disabled:
            return
        url = cfg.traces_endpoint()
        headers = self._build_headers(cfg)
        remaining: list[Dict[str, Any]] = []
        try:
            with httpx.Client(timeout=cfg.timeout_seconds) as sync_client:
                for idx, payload in enumerate(payloads):
                    if self._stop.is_set():
                        remaining.extend(payloads[idx:])
                        break
                    body = dumps_json(payload)
                    delivered = False
                    delays = (0.05, 0.2, 0.75)
                    for delay in (*delays, None):
                        try:
                            response = sync_client.post(url, content=body, headers=headers)
                            if response.status_code < 500:
                                delivered = True
                                if response.status_code >= 400:
                                    logger.warning(
                                        "verdictlens: disk flush ingest rejected (%s): %s",
                                        response.status_code,
                                        response.text[:512],
                                    )
                                break
                        except Exception as exc:
                            logger.debug("verdictlens: disk flush post failed: %s", exc, exc_info=True)
                        if delay is None:
                            break
                        time.sleep(delay)
                    if not delivered:
                        remaining.append(payload)
        except Exception as exc:
            logger.debug("verdictlens: disk flush client error: %s", exc, exc_info=True)
            remaining = payloads

        self._disk.clear_file(path)
        for payload in remaining:
            self._disk.enqueue(payload)


def get_client() -> VerdictLensClient:
    """
    Return the process-wide :class:`VerdictLensClient`, constructing if needed.

    :returns: Shared client instance.
    """
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = VerdictLensClient()
        return _CLIENT


def set_client(client: Optional[VerdictLensClient]) -> None:
    """
    Replace the shared client (primarily for tests).

    :param client: New client or None to clear.
    :returns: None
    """
    global _CLIENT
    with _CLIENT_LOCK:
        old = _CLIENT
        _CLIENT = client
    if old is not None:
        old.close()


def reset_client() -> None:
    """
    Close and drop the cached shared client.

    :returns: None
    """
    set_client(None)


# ---------------------------------------------------------------------------
# Dataset & evaluation convenience helpers (synchronous HTTP)
# ---------------------------------------------------------------------------

def _api_url(path: str) -> str:
    """Resolve a full API URL from the active config."""
    cfg = get_config()
    return cfg.base_url.rstrip("/") + path


def _api_headers() -> Dict[str, str]:
    """Standard headers for API calls."""
    cfg = get_config()
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["X-VerdictLens-Key"] = cfg.api_key
    if cfg.workspace:
        headers["X-VerdictLens-Workspace"] = cfg.workspace
    if cfg.project:
        headers["X-VerdictLens-Project"] = cfg.project
    headers.update(dict(cfg.extra_headers))
    return headers


def _api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Synchronous GET against the backend API."""
    with httpx.Client(timeout=get_config().timeout_seconds) as c:
        resp = c.get(_api_url(path), headers=_api_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def _api_post(path: str, body: Dict[str, Any]) -> Any:
    """Synchronous POST against the backend API."""
    with httpx.Client(timeout=get_config().timeout_seconds) as c:
        resp = c.post(_api_url(path), headers=_api_headers(), json=body)
        resp.raise_for_status()
        return resp.json()


def _api_delete(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Synchronous DELETE against the backend API."""
    with httpx.Client(timeout=get_config().timeout_seconds) as c:
        resp = c.delete(_api_url(path), headers=_api_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def create_dataset(name: str, description: str = "") -> Dict[str, Any]:
    """
    Create a new dataset on the VerdictLens server.

    :param name: Human-readable dataset name.
    :param description: Optional description.
    :returns: Created dataset dict (id, name, description, created_at, …).
    """
    return _api_post("/datasets", {"name": name, "description": description})


def list_datasets() -> list:
    """
    List all datasets visible to the current workspace.

    :returns: List of dataset dicts.
    """
    return _api_get("/datasets")


def add_example(
    dataset_id: str,
    *,
    inputs: Any,
    outputs: Any = None,
    expected: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Add an example to a dataset.

    :param dataset_id: Target dataset ID.
    :param inputs: Example inputs (any JSON-serializable value).
    :param outputs: Stored outputs (optional).
    :param expected: Expected/gold outputs for scoring (optional).
    :param metadata: Arbitrary metadata dict (optional).
    :returns: Created example dict.
    """
    body: Dict[str, Any] = {"inputs": inputs}
    if outputs is not None:
        body["outputs"] = outputs
    if expected is not None:
        body["expected"] = expected
    if metadata is not None:
        body["metadata"] = metadata
    return _api_post(f"/datasets/{dataset_id}/examples", body)


def list_examples(dataset_id: str) -> list:
    """
    List all examples in a dataset.

    :param dataset_id: Dataset ID.
    :returns: List of example dicts.
    """
    return _api_get(f"/datasets/{dataset_id}/examples")


def delete_example(dataset_id: str, example_id: str) -> Dict[str, Any]:
    """
    Delete a specific example from a dataset.

    :param dataset_id: Dataset ID.
    :param example_id: Example ID.
    :returns: Deletion confirmation dict.
    """
    return _api_delete(f"/datasets/{dataset_id}/examples/{example_id}")
