"""
Genesis Engine — Redis Swarm Cache
Pub/sub for real-time alpha signals, market data cache, position state, and agent heartbeat.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import redis.asyncio as redis


class RedisSwarmCache:
    """
    Async Redis interface for the Genesis Engine swarm layer.

    Channels:
      - genesis:signals    -> Alpha signals from strategies
      - genesis:trades     -> Execution fills
      - genesis:heartbeat  -> Agent health checks
      - genesis:alerts     -> Risk circuit breakers
    """

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self._redis: Optional[redis.Redis] = None

    async def connect(self):
        self._redis = redis.Redis(
            host=self.host,
            port=self.port,
            db=self.db,
            decode_responses=True,
        )

    async def disconnect(self):
        if self._redis:
            await self._redis.close()

    # ------------------------------------------------------------------
    # Market data cache
    # ------------------------------------------------------------------

    async def set_book(self, venue: str, symbol: str, book: Dict[str, Any], ttl: int = 5):
        key = f"book:{venue}:{symbol}"
        await self._redis.setex(key, ttl, json.dumps(book))

    async def get_book(self, venue: str, symbol: str) -> Optional[Dict[str, Any]]:
        key = f"book:{venue}:{symbol}"
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    async def set_funding(self, venue: str, symbol: str, rate: float, ttl: int = 300):
        key = f"funding:{venue}:{symbol}"
        await self._redis.setex(key, ttl, str(rate))

    async def get_funding(self, venue: str, symbol: str) -> Optional[float]:
        key = f"funding:{venue}:{symbol}"
        raw = await self._redis.get(key)
        return float(raw) if raw else None

    # ------------------------------------------------------------------
    # Position & risk state
    # ------------------------------------------------------------------

    async def set_position(self, venue: str, symbol: str, size: float):
        key = f"pos:{venue}:{symbol}"
        await self._redis.set(key, str(size))

    async def get_position(self, venue: str, symbol: str) -> float:
        key = f"pos:{venue}:{symbol}"
        raw = await self._redis.get(key)
        return float(raw) if raw else 0.0

    async def set_portfolio_value(self, value: float):
        await self._redis.set("portfolio:value", str(value))

    async def get_portfolio_value(self) -> float:
        raw = await self._redis.get("portfolio:value")
        return float(raw) if raw else 0.0

    # ------------------------------------------------------------------
    # Pub/Sub — Alpha signals
    # ------------------------------------------------------------------

    async def publish_signal(self, channel: str, signal: Dict[str, Any]):
        await self._redis.publish(channel, json.dumps(signal))

    async def subscribe(self, channel: str):
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    # ------------------------------------------------------------------
    # Agent registry
    # ------------------------------------------------------------------

    async def register_agent(self, agent_id: str, agent_type: str, metadata: Dict[str, Any]):
        key = f"agent:{agent_id}"
        payload = {"type": agent_type, "heartbeat": time.time(), **metadata}
        await self._redis.hset(key, mapping={k: json.dumps(v) for k, v in payload.items()})

    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        key = f"agent:{agent_id}"
        raw = await self._redis.hgetall(key)
        if not raw:
            return None
        return {k: json.loads(v) for k, v in raw.items()}


import time
