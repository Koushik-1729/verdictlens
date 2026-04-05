"""
Runtime configuration for the VerdictLens SDK (endpoint, auth, queue paths, OTel).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Optional
from urllib.parse import urljoin

_DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def _env_bool(name: str, default: bool) -> bool:
    """
    Parse a boolean environment variable.

    :param name: Environment variable name.
    :param default: Value used when unset or empty.
    :returns: Parsed boolean.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class VerdictLensConfig:
    """
    Immutable SDK configuration.

    :param base_url: Ingest API base URL (without trailing path segments for traces).
    :param api_key: Optional bearer/API key sent as ``Authorization: Bearer`` or
                    ``X-VerdictLens-Key`` header.
    :param timeout_seconds: HTTP timeout for ingest requests.
    :param max_queue_bytes: Approximate cap for the on-disk offline queue directory.
    :param queue_dir: Directory for durable offline queue files.
    :param disabled: When True, the SDK becomes a no-op (no network, no disk writes).
    :param extra_headers: Additional static HTTP headers for ingest.
    :param otel_export: When True, also emit spans to an OTel collector in parallel.
    :param otel_endpoint: OTLP gRPC endpoint (default ``http://localhost:4317``).
    :param otel_service_name: OTel service.name resource attribute.
    """

    base_url: str = _DEFAULT_BASE_URL
    api_key: Optional[str] = None
    workspace: Optional[str] = None
    project: Optional[str] = None
    timeout_seconds: float = 10.0
    max_queue_bytes: int = 256 * 1024 * 1024
    queue_dir: Optional[str] = None
    disabled: bool = False
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    otel_export: bool = False
    otel_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "verdictlens"

    def traces_endpoint(self) -> str:
        """
        Resolve the full URL for trace ingestion.

        :returns: Absolute URL for ``POST /traces`` (or configured path).
        """
        base = self.base_url.rstrip("/") + "/"
        return urljoin(base, "traces")

    def with_updates(self, **kwargs: Any) -> "VerdictLensConfig":
        """
        Return a new configuration with selected fields replaced.

        :param kwargs: Fields to override on a copy.
        :returns: New :class:`VerdictLensConfig` instance.
        """
        data = {
            "base_url": self.base_url,
            "api_key": self.api_key,
            "workspace": self.workspace,
            "project": self.project,
            "timeout_seconds": self.timeout_seconds,
            "max_queue_bytes": self.max_queue_bytes,
            "queue_dir": self.queue_dir,
            "disabled": self.disabled,
            "extra_headers": dict(self.extra_headers),
            "otel_export": self.otel_export,
            "otel_endpoint": self.otel_endpoint,
            "otel_service_name": self.otel_service_name,
        }
        for key, value in kwargs.items():
            if key not in data:
                raise TypeError(f"Unknown config field: {key!r}")
            data[key] = value
        return VerdictLensConfig(
            base_url=str(data["base_url"]),
            api_key=data["api_key"],
            workspace=data["workspace"],
            project=data["project"],
            timeout_seconds=float(data["timeout_seconds"]),
            max_queue_bytes=int(data["max_queue_bytes"]),
            queue_dir=data["queue_dir"],
            disabled=bool(data["disabled"]),
            extra_headers=data["extra_headers"],
            otel_export=bool(data["otel_export"]),
            otel_endpoint=str(data["otel_endpoint"]),
            otel_service_name=str(data["otel_service_name"]),
        )


_CONFIG_LOCK = threading.RLock()
_CONFIG: Optional[VerdictLensConfig] = None


def get_config() -> VerdictLensConfig:
    """
    Return the process-wide SDK configuration, creating defaults if needed.

    :returns: Active :class:`VerdictLensConfig`.
    """
    global _CONFIG
    with _CONFIG_LOCK:
        if _CONFIG is None:
            _CONFIG = VerdictLensConfig(
                base_url=os.environ.get("VERDICTLENS_BASE_URL", _DEFAULT_BASE_URL).strip()
                or _DEFAULT_BASE_URL,
                api_key=os.environ.get("VERDICTLENS_API_KEY") or None,
                workspace=os.environ.get("VERDICTLENS_WORKSPACE") or None,
                project=os.environ.get("VERDICTLENS_PROJECT") or None,
                disabled=_env_bool("VERDICTLENS_DISABLED", False),
                queue_dir=os.environ.get("VERDICTLENS_QUEUE_DIR") or None,
                otel_export=_env_bool("VERDICTLENS_OTEL_EXPORT", False),
                otel_endpoint=os.environ.get("VERDICTLENS_OTEL_ENDPOINT", "http://localhost:4317"),
                otel_service_name=os.environ.get("VERDICTLENS_OTEL_SERVICE_NAME", "verdictlens"),
            )
        return _CONFIG


def configure(
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    workspace: Optional[str] = None,
    project: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    max_queue_bytes: Optional[int] = None,
    queue_dir: Optional[str] = None,
    disabled: Optional[bool] = None,
    extra_headers: Optional[MutableMapping[str, str]] = None,
    otel_export: Optional[bool] = None,
    otel_endpoint: Optional[str] = None,
    otel_service_name: Optional[str] = None,
    reset_client: bool = True,
) -> VerdictLensConfig:
    """
    Update global SDK settings and optionally reset the shared HTTP client.

    :param base_url: Backend base URL.
    :param api_key: Optional API key (sent as ``Authorization: Bearer`` and
                    ``X-VerdictLens-Key``).
    :param timeout_seconds: Per-request timeout.
    :param max_queue_bytes: Offline queue size budget.
    :param queue_dir: Offline queue directory override.
    :param disabled: Disable all instrumentation side effects.
    :param extra_headers: Merge/replace default extra headers (merged shallowly).
    :param otel_export: Enable OTel export in parallel with native transport.
    :param otel_endpoint: OTLP gRPC endpoint.
    :param otel_service_name: OTel service.name resource attribute.
    :param reset_client: When True, drop the cached :class:`~verdictlens.client.VerdictLensClient`.
    :returns: The new active configuration.
    """
    global _CONFIG
    with _CONFIG_LOCK:
        current = get_config()
        updates: dict[str, Any] = {}
        if base_url is not None:
            updates["base_url"] = base_url
        if api_key is not None:
            updates["api_key"] = api_key
        if workspace is not None:
            updates["workspace"] = workspace
        if project is not None:
            updates["project"] = project
        if timeout_seconds is not None:
            updates["timeout_seconds"] = timeout_seconds
        if max_queue_bytes is not None:
            updates["max_queue_bytes"] = max_queue_bytes
        if queue_dir is not None:
            updates["queue_dir"] = queue_dir
        if disabled is not None:
            updates["disabled"] = disabled
        if extra_headers is not None:
            merged = dict(current.extra_headers)
            merged.update(dict(extra_headers))
            updates["extra_headers"] = merged
        if otel_export is not None:
            updates["otel_export"] = otel_export
        if otel_endpoint is not None:
            updates["otel_endpoint"] = otel_endpoint
        if otel_service_name is not None:
            updates["otel_service_name"] = otel_service_name
        _CONFIG = current.with_updates(**updates) if updates else current
        active = _CONFIG

    if active.otel_export:
        from verdictlens.otel_export import init_otel
        init_otel(service_name=active.otel_service_name, otel_endpoint=active.otel_endpoint)

    if reset_client:
        from verdictlens.client import reset_client as _reset_client
        _reset_client()
    return active
