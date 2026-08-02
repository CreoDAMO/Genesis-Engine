"""
Genesis Engine — Polymarket CLOB Client
Async REST + WebSocket client for Polymarket's Central Limit Order Book.
Handles: market data, order book reconstruction, order placement, position tracking.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed


@dataclass
class PolymarketOrder:
    side: str  # "BUY" | "SELL"
    price: Decimal
    size: Decimal
    token_id: str
    order_type: str = "GTC"  # GTC, FOK, IOC
    client_order_id: Optional[str] = None
    nonce: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class PolymarketBookLevel:
    price: Decimal
    size: Decimal


@dataclass
class PolymarketOrderBook:
    market_id: str
    token_id: str
    bids: List[PolymarketBookLevel] = field(default_factory=list)
    asks: List[PolymarketBookLevel] = field(default_factory=list)
    timestamp: float = 0.0
    sequence: int = 0

    def best_bid(self) -> Optional[Decimal]:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> Optional[Decimal]:
        return self.asks[0].price if self.asks else None

    def mid(self) -> Optional[Decimal]:
        bb = self.best_bid()
        ba = self.best_ask()
        if bb is not None and ba is not None:
            return (bb + ba) / 2
        return None

    def spread(self) -> Optional[Decimal]:
        bb = self.best_bid()
        ba = self.best_ask()
        if bb is not None and ba is not None:
            return ba - bb
        return None

    def spread_bps(self) -> Optional[Decimal]:
        sp = self.spread()
        mid = self.mid()
        if sp is not None and mid and mid > 0:
            return (sp / mid) * Decimal("10000")
        return None

    def imbalance(self) -> Decimal:
        bid_vol = sum(l.size for l in self.bids)
        ask_vol = sum(l.size for l in self.asks)
        total = bid_vol + ask_vol
        if total == 0:
            return Decimal("0")
        return (bid_vol - ask_vol) / total


class PolymarketClient:
    """
    Async Polymarket CLOB client.

    Usage:
        client = PolymarketClient(api_key, secret, passphrase)
        await client.start()
        book = await client.get_order_book("0x123...", "0xabc...")
        await client.subscribe_book("0xabc...", callback)
        await client.stop()
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        base_url: str = "https://clob.polymarket.com",
        ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market",
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self.timeout = timeout

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        self._reconnect_delay = 5.0

        # Order book cache: token_id -> PolymarketOrderBook
        self._books: Dict[str, PolymarketOrderBook] = {}
        self._book_callbacks: Dict[str, Callable[[PolymarketOrderBook], None]] = {}

        # Position cache
        self._positions: Dict[str, Decimal] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Initialize HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        self._running = True

    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """HMAC-SHA256 signature for Polymarket CLOB."""
        message = timestamp + method.upper() + path + body
        sig = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return sig

    def _auth_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        ts = str(int(time.time()))
        sig = self._sign(ts, method, path, body)
        return {
            "POLY-API-KEY": self.api_key,
            "POLY-SIGNATURE": sig,
            "POLY-TIMESTAMP": ts,
            "POLY-PASSPHRASE": self.passphrase,
        }

    # ------------------------------------------------------------------
    # REST — Public
    # ------------------------------------------------------------------

    async def get_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Fetch markets list."""
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
        }
        url = f"{self.base_url}/markets?{urlencode(params)}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("data", [])

    async def get_market(self, market_id: str) -> Dict[str, Any]:
        """Fetch single market details."""
        url = f"{self.base_url}/markets/{market_id}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_order_book(
        self, market_id: str, token_id: str
    ) -> PolymarketOrderBook:
        """Fetch L2 order book snapshot."""
        url = f"{self.base_url}/book?market={market_id}&asset_id={token_id}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            book = self._parse_book(data, market_id, token_id)
            self._books[token_id] = book
            return book

    def _parse_book(
        self, data: Dict[str, Any], market_id: str, token_id: str
    ) -> PolymarketOrderBook:
        bids = [
            PolymarketBookLevel(price=Decimal(str(p)), size=Decimal(str(s)))
            for p, s in data.get("bids", [])
        ]
        asks = [
            PolymarketBookLevel(price=Decimal(str(p)), size=Decimal(str(s)))
            for p, s in data.get("asks", [])
        ]
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        return PolymarketOrderBook(
            market_id=market_id,
            token_id=token_id,
            bids=bids,
            asks=asks,
            timestamp=time.time(),
            sequence=data.get("sequence", 0),
        )

    async def get_trades(
        self, market_id: str, token_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Recent trades for a market."""
        url = f"{self.base_url}/trades?market={market_id}&asset_id={token_id}&limit={limit}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("trades", [])

    async def get_fees(self) -> Dict[str, Any]:
        """Current fee schedule."""
        url = f"{self.base_url}/fees"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # REST — Private
    # ------------------------------------------------------------------

    async def get_balance(self) -> Dict[str, Any]:
        """USDCe balance."""
        path = "/balance"
        url = f"{self.base_url}{path}"
        headers = self._auth_headers("GET", path)
        async with self._session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Open positions."""
        path = "/positions"
        url = f"{self.base_url}{path}"
        headers = self._auth_headers("GET", path)
        async with self._session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            positions = data if isinstance(data, list) else data.get("positions", [])
            # Update cache
            for pos in positions:
                tid = pos.get("asset_id") or pos.get("token_id")
                if tid:
                    self._positions[tid] = Decimal(str(pos.get("size", 0)))
            return positions

    async def place_order(self, order: PolymarketOrder) -> Dict[str, Any]:
        """Place an order on the CLOB."""
        path = "/order"
        url = f"{self.base_url}{path}"
        payload = {
            "side": order.side,
            "price": str(order.price),
            "size": str(order.size),
            "token_id": order.token_id,
            "type": order.order_type,
            "nonce": order.nonce,
        }
        if order.client_order_id:
            payload["client_order_id"] = order.client_order_id

        body = json.dumps(payload, separators=(",", ":"))
        headers = self._auth_headers("POST", path, body)
        headers["Content-Type"] = "application/json"

        async with self._session.post(url, headers=headers, data=body) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an order."""
        path = f"/order/{order_id}"
        url = f"{self.base_url}{path}"
        headers = self._auth_headers("DELETE", path)
        async with self._session.delete(url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def cancel_all(self) -> Dict[str, Any]:
        """Cancel all open orders."""
        path = "/orders"
        url = f"{self.base_url}{path}"
        headers = self._auth_headers("DELETE", path)
        async with self._session.delete(url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        """List open orders."""
        path = "/orders"
        url = f"{self.base_url}{path}"
        headers = self._auth_headers("GET", path)
        async with self._session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, list) else data.get("orders", [])

    # ------------------------------------------------------------------
    # WebSocket — Order Book Streaming
    # ------------------------------------------------------------------

    async def subscribe_book(
        self,
        token_id: str,
        callback: Callable[[PolymarketOrderBook], None],
        market_id: str = "",
    ):
        """Subscribe to real-time order book updates."""
        self._book_callbacks[token_id] = callback
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self):
        """WebSocket connection manager with auto-reconnect."""
        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self._ws = ws
                    # Subscribe to all tracked books
                    for tid in self._book_callbacks:
                        sub_msg = {
                            "type": "subscribe",
                            "channel": "orderbook",
                            "payload": {"asset_id": tid},
                        }
                        await ws.send(json.dumps(sub_msg))

                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_ws_message(message)
            except ConnectionClosed:
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)
            except Exception as e:
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)

    async def _handle_ws_message(self, raw: str):
        try:
            msg = json.loads(raw)
            msg_type = msg.get("type", "")
            if msg_type == "orderbook":
                payload = msg.get("payload", {})
                tid = payload.get("asset_id")
                if tid and tid in self._book_callbacks:
                    # Merge delta into cached book
                    book = self._books.get(tid)
                    if book:
                        self._apply_book_delta(book, payload)
                        book.timestamp = time.time()
                        cb = self._book_callbacks.get(tid)
                        if cb:
                            cb(book)
        except Exception:
            pass

    def _apply_book_delta(self, book: PolymarketOrderBook, delta: Dict[str, Any]):
        """Apply L2 delta update to cached book."""
        # Simple full-replace for now; production would use sequence numbers
        bids = [
            PolymarketBookLevel(price=Decimal(str(p)), size=Decimal(str(s)))
            for p, s in delta.get("bids", [])
        ]
        asks = [
            PolymarketBookLevel(price=Decimal(str(p)), size=Decimal(str(s)))
            for p, s in delta.get("asks", [])
        ]
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        book.bids = bids
        book.asks = asks
        book.sequence = delta.get("sequence", book.sequence)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_cached_book(self, token_id: str) -> Optional[PolymarketOrderBook]:
        return self._books.get(token_id)

    def get_cached_position(self, token_id: str) -> Decimal:
        return self._positions.get(token_id, Decimal("0"))
