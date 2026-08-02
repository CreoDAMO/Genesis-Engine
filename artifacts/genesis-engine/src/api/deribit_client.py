"""
Genesis Engine — Deribit Client
Async REST + WebSocket for options, futures, and perp trading.
Deribit uses signature-based auth (client_id + client_secret + timestamp).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed


@dataclass
class DeribitBookLevel:
    price: Decimal
    size: Decimal


@dataclass
class DeribitOrderBook:
    instrument: str
    bids: List[DeribitBookLevel] = field(default_factory=list)
    asks: List[DeribitBookLevel] = field(default_factory=list)
    timestamp: float = 0.0
    change_id: int = 0

    def best_bid(self) -> Optional[Decimal]:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> Optional[Decimal]:
        return self.asks[0].price if self.asks else None

    def mid(self) -> Optional[Decimal]:
        bb = self.best_bid()
        ba = self.best_ask()
        if bb and ba:
            return (bb + ba) / 2
        return None


class DeribitClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = "https://www.deribit.com/api/v2",
        ws_url: str = "wss://www.deribit.com/ws/api/v2",
        testnet: bool = False,
        timeout: float = 30.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.testnet = testnet
        self.timeout = timeout

        if testnet:
            self.base_url = "https://test.deribit.com/api/v2"
            self.ws_url = "wss://test.deribit.com/ws/api/v2"
        else:
            self.base_url = base_url.rstrip("/")
            self.ws_url = ws_url

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        self._reconnect_delay = 5.0
        self._ws_id = 0

        self._books: Dict[str, DeribitOrderBook] = {}
        self._book_callbacks: Dict[str, Callable[[DeribitOrderBook], None]] = {}
        self._funding_cache: Dict[str, Dict[str, Any]] = {}
        self._access_token: Optional[str] = None

    async def start(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        self._running = True
        await self._authenticate()

    async def stop(self):
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

    def _auth_signature(self) -> Dict[str, str]:
        ts = str(int(time.time()) * 1000)
        nonce = str(int(time.time()))
        data = ""
        msg = f"{ts}\n{nonce}\n{data}"
        sig = hmac.new(self.client_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "client_id": self.client_id,
            "timestamp": ts,
            "nonce": nonce,
            "signature": sig,
            "data": data,
        }

    async def _authenticate(self):
        """Get OAuth2 access token."""
        auth = self._auth_signature()
        url = f"{self.base_url}/public/auth"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "public/auth",
            "params": {
                "grant_type": "client_signature",
                **auth,
            },
        }
        async with self._session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._access_token = data.get("result", {}).get("access_token")

    def _auth_headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._access_token:
            h["Authorization"] = f"Bearer {self._access_token}"
        return h

    def _rpc(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        self._ws_id += 1
        return {
            "jsonrpc": "2.0",
            "id": self._ws_id,
            "method": method,
            "params": params or {},
        }

    # ------------------------------------------------------------------
    # REST — Public
    # ------------------------------------------------------------------

    async def get_funding_rate(self, instrument: str) -> Dict[str, Any]:
        url = f"{self.base_url}/public/get_funding_rate_history"
        payload = self._rpc("public/get_funding_rate_history", {
            "instrument_name": instrument,
            "count": 1,
        })
        async with self._session.get(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            result = data.get("result", [])
            if result:
                self._funding_cache[instrument] = result[0]
            return result[0] if result else {}

    async def get_order_book(self, instrument: str, depth: int = 50) -> DeribitOrderBook:
        url = f"{self.base_url}/public/get_order_book"
        payload = self._rpc("public/get_order_book", {
            "instrument_name": instrument,
            "depth": depth,
        })
        async with self._session.get(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            result = data.get("result", {})
            bids = [DeribitBookLevel(Decimal(str(b[0])), Decimal(str(b[1]))) for b in result.get("bids", [])]
            asks = [DeribitBookLevel(Decimal(str(a[0])), Decimal(str(a[1]))) for a in result.get("asks", [])]
            book = DeribitOrderBook(
                instrument=instrument,
                bids=sorted(bids, key=lambda x: x.price, reverse=True),
                asks=sorted(asks, key=lambda x: x.price),
                timestamp=time.time(),
                change_id=result.get("change_id", 0),
            )
            self._books[instrument] = book
            return book

    async def get_instruments(self, currency: str = "BTC", kind: str = "future") -> List[Dict[str, Any]]:
        url = f"{self.base_url}/public/get_instruments"
        payload = self._rpc("public/get_instruments", {
            "currency": currency,
            "kind": kind,
            "expired": False,
        })
        async with self._session.get(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", [])

    async def get_tickers(self, instrument: str) -> Dict[str, Any]:
        url = f"{self.base_url}/public/ticker"
        payload = self._rpc("public/ticker", {"instrument_name": instrument})
        async with self._session.get(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", {})

    # ------------------------------------------------------------------
    # REST — Private
    # ------------------------------------------------------------------

    async def get_account(self) -> Dict[str, Any]:
        url = f"{self.base_url}/private/get_account_summary"
        payload = self._rpc("private/get_account_summary", {"currency": "USDT"})
        headers = self._auth_headers()
        async with self._session.get(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", {})

    async def get_positions(self, currency: str = "USDT") -> List[Dict[str, Any]]:
        url = f"{self.base_url}/private/get_positions"
        payload = self._rpc("private/get_positions", {"currency": currency})
        headers = self._auth_headers()
        async with self._session.get(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", [])

    async def place_order(
        self,
        instrument: str,
        side: str,  # buy / sell
        amount: Decimal,
        order_type: str = "market",  # market, limit, stop_market, etc.
        price: Optional[Decimal] = None,
        label: str = "genesis",
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/private/{side}"
        params = {
            "instrument_name": instrument,
            "amount": float(amount),
            "type": order_type,
            "label": label,
        }
        if order_type == "limit" and price is not None:
            params["price"] = float(price)
        payload = self._rpc(f"private/{side}", params)
        headers = self._auth_headers()
        async with self._session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", {})

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/private/cancel"
        payload = self._rpc("private/cancel", {"order_id": order_id})
        headers = self._auth_headers()
        async with self._session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", {})

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def subscribe_book(self, instrument: str, callback: Callable[[DeribitOrderBook], None]):
        self._book_callbacks[instrument] = callback
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self):
        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self._ws = ws
                    # Auth over WS
                    if self._access_token:
                        await ws.send(json.dumps(self._rpc("public/auth", {
                            "grant_type": "client_credentials",
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                        })))
                    # Subscribe to books
                    for inst in self._book_callbacks:
                        await ws.send(json.dumps(self._rpc("public/subscribe", {
                            "channels": [f"book.{inst}.100ms"],
                        })))
                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_ws_message(message)
            except ConnectionClosed:
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)
            except Exception:
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)

    async def _handle_ws_message(self, raw: str):
        try:
            msg = json.loads(raw)
            method = msg.get("method", "")
            if method == "subscription":
                params = msg.get("params", {})
                channel = params.get("channel", "")
                data = params.get("data", {})
                if "book" in channel:
                    inst = channel.split(".")[1]
                    if inst in self._book_callbacks:
                        book = self._books.get(inst, DeribitOrderBook(instrument=inst))
                        bids = [DeribitBookLevel(Decimal(str(b[0])), Decimal(str(b[1]))) for b in data.get("bids", [])]
                        asks = [DeribitBookLevel(Decimal(str(a[0])), Decimal(str(a[1]))) for a in data.get("asks", [])]
                        if bids:
                            book.bids = sorted(bids, key=lambda x: x.price, reverse=True)
                        if asks:
                            book.asks = sorted(asks, key=lambda x: x.price)
                        book.timestamp = time.time()
                        book.change_id = data.get("change_id", book.change_id)
                        self._books[inst] = book
                        cb = self._book_callbacks.get(inst)
                        if cb:
                            cb(book)
        except Exception:
            pass

    def get_cached_book(self, instrument: str) -> Optional[DeribitOrderBook]:
        return self._books.get(instrument)

    def get_cached_funding(self, instrument: str) -> Optional[Dict[str, Any]]:
        return self._funding_cache.get(instrument)
