"""
WebSocket broadcast manager for real-time trace streaming.

Maintains an in-process set of connected WebSocket clients and publishes
every ingested trace to all of them.  When Redis is reachable, the manager
also publishes/subscribes on a Redis Pub/Sub channel so that multiple API
replicas share the same live feed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("verdictlens.live")

_REDIS_CHANNEL = "verdictlens:live_traces"


class ConnectionManager:
    """
    Manages WebSocket connections and broadcasts incoming trace payloads.
    """

    def __init__(self) -> None:
        """
        Initialize the set of active connections and Redis handles.
        """
        self._connections: Set[WebSocket] = set()
        self._redis: Optional[Any] = None
        self._subscriber_task: Optional[asyncio.Task[None]] = None

    async def start(self, redis_url: Optional[str] = None) -> None:
        """
        Optionally connect to Redis and start the Pub/Sub listener.

        :param redis_url: Redis connection URL or None to skip.
        :returns: None
        """
        if not redis_url:
            return
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]

            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            self._subscriber_task = asyncio.create_task(self._redis_listener())
            logger.info("verdictlens: Redis Pub/Sub connected (%s)", redis_url)
        except Exception as exc:
            logger.warning("verdictlens: Redis unavailable (%s) — local-only live feed", exc)
            self._redis = None

    async def stop(self) -> None:
        """
        Tear down Redis connections and background tasks.

        :returns: None
        """
        if self._subscriber_task is not None:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except (asyncio.CancelledError, Exception):
                pass
            self._subscriber_task = None
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

    async def connect(self, ws: WebSocket) -> None:
        """
        Accept a WebSocket and add it to the active set.

        :param ws: Incoming WebSocket connection.
        :returns: None
        """
        await ws.accept()
        self._connections.add(ws)
        logger.debug("verdictlens: WebSocket connected (%d active)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        """
        Remove a WebSocket from the active set.

        :param ws: Disconnecting WebSocket.
        :returns: None
        """
        self._connections.discard(ws)
        logger.debug("verdictlens: WebSocket disconnected (%d active)", len(self._connections))

    async def broadcast_trace(self, payload: Dict[str, Any]) -> None:
        """
        Send a trace payload to all connected WebSockets and publish to Redis.

        :param payload: JSON-serializable trace dict.
        :returns: None
        """
        message = json.dumps(payload, ensure_ascii=False, default=str)

        if self._redis is not None:
            try:
                await self._redis.publish(_REDIS_CHANNEL, message)
                return
            except Exception as exc:
                logger.debug("verdictlens: Redis publish failed (%s), broadcasting locally", exc)

        await self._broadcast_local(message)

    async def _broadcast_local(self, message: str) -> None:
        """
        Send a pre-serialized message to all in-process WebSocket connections.

        :param message: JSON string.
        :returns: None
        """
        stale: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except (WebSocketDisconnect, RuntimeError, Exception):
                stale.append(ws)
        for ws in stale:
            self._connections.discard(ws)

    async def _redis_listener(self) -> None:
        """
        Background task that subscribes to the Redis channel and relays
        messages to local WebSocket connections.

        :returns: None
        """
        if self._redis is None:
            return
        try:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(_REDIS_CHANNEL)
            async for raw_msg in pubsub.listen():
                if raw_msg is None:
                    continue
                if raw_msg.get("type") != "message":
                    continue
                data = raw_msg.get("data")
                if isinstance(data, str):
                    await self._broadcast_local(data)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("verdictlens: Redis subscriber crashed: %s", exc)


manager = ConnectionManager()
