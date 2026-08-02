"""
Genesis Engine — Bybit V5 Unified Trading Client
Async REST + WebSocket for USDT perps, positions, and order execution.
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
class BybitBookLevel:
    price: Decimal
    size: Decimal


@dataclass
class BybitOrderBook:
    symbol: str
    bids: List[BybitBookLevel] = field(default_factory=list)
    asks: List[BybitBookLevel] = field(default_factory=list)
    timestamp: float = 0.0
    seq: int = 0

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


class BybitClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.bybit.com",
        ws_url: str = "wss://stream.bybit.com/v5/public/linear",
        testnet: bool = False,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.timeout = timeout

        if testnet:
            self.base_url = "https://api-testnet.bybit.com"
            self.ws_url = "wss://stream-testnet.bybit.com/v5/public/linear"
        else:
            self.base_url = base_url.rstrip("/")
            self.ws_url = ws_url

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        self._reconnect_delay = 5.0

        self._books: Dict[str, BybitOrderBook] = {}
        self._book_callbacks: Dict[str, Callable[[BybitOrderBook], None]] = {}
        self._funding_cache: Dict[str, Dict[str, Any]] = {}

    async def start(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        self._running = True

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

    def _auth_headers(self) -> Dict[str, str]:
        ts = str(int(time.time() * 1000))
        recv_window = "5000"
        sign_payload = ts + self.api_key + recv_window
        signature = hmac.new(
            self.api_secret.encode(), sign_payload.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": recv_window,
        }

    # ------------------------------------------------------------------
    # REST — Public
    # ------------------------------------------------------------------

    async def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v5/market/funding/history?category=linear&symbol={symbol}&limit=1"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            result = data.get("result", {}).get("list", [])
            if result:
                self._funding_cache[symbol] = result[0]
            return result[0] if result else {}

    async def get_all_funding_rates(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/v5/market/tickers?category=linear"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            result = data.get("result", {}).get("list", [])
            for d in result:
                self._funding_cache[d.get("symbol", "")] = d
            return result

    async def get_order_book(self, symbol: str, limit: int = 50) -> BybitOrderBook:
        url = f"{self.base_url}/v5/market/orderbook?category=linear&symbol={symbol}&limit={limit}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            result = data.get("result", {})
            bids = [BybitBookLevel(Decimal(b[0]), Decimal(b[1])) for b in result.get("b", [])]
            asks = [BybitBookLevel(Decimal(a[0]), Decimal(a[1])) for a in result.get("a", [])]
            book = BybitOrderBook(
                symbol=symbol,
                bids=sorted(bids, key=lambda x: x.price, reverse=True),
                asks=sorted(asks, key=lambda x: x.price),
                timestamp=time.time(),
                seq=result.get("seq", 0),
            )
            self._books[symbol] = book
            return book

    async def get_tickers(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/v5/market/tickers?category=linear"
        if symbol:
            url += f"&symbol={symbol}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", {}).get("list", [])

    # ------------------------------------------------------------------
    # REST — Private
    # ------------------------------------------------------------------

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/v5/position/list?category=linear&settleCoin=USDT"
        if symbol:
            url += f"&symbol={symbol}"
        headers = self._auth_headers()
        async with self._session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("result", {}).get("list", [])

    async def place_order(
        self,
        symbol: str,
        side: str,  # Buy / Sell
        order_type: str,  # Market / Limit
        qty: Decimal,
        price: Optional[Decimal] = None,
        time_in_force: str = "GTC",
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v5/order/create"
        body = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
        }
        if order_type == "Limit":
            body["price"] = str(price)
            body["timeInForce"] = time_in_force
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        async with self._session.post(url, headers=headers, json=body) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v5/order/cancel"
        body = {"category": "linear", "symbol": symbol, "orderId": order_id}
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        async with self._session.post(url, headers=headers, json=body) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def subscribe_book(self, symbol: str, callback: Callable[[BybitOrderBook], None]):
        self._book_callbacks[symbol] = callback
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self):
        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self._ws = ws
                    for sym in self._book_callbacks:
                        await ws.send(json.dumps({
                            "op": "subscribe",
                            "args": [{"channel": "orderbook", "symbol": sym, "depth": 50}],
                        }))
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
            topic = msg.get("topic", "")
            if "orderbook" in topic:
                data = msg.get("data", {})
                symbol = data.get("s", "")
                if symbol in self._book_callbacks:
                    book = self._books.get(symbol, BybitOrderBook(symbol=symbol))
                    bids = [BybitBookLevel(Decimal(b[0]), Decimal(b[1])) for b in data.get("b", [])]
                    asks = [BybitBookLevel(Decimal(a[0]), Decimal(a[1])) for a in data.get("a", [])]
                    if bids:
                        book.bids = sorted(bids, key=lambda x: x.price, reverse=True)
                    if asks:
                        book.asks = sorted(asks, key=lambda x: x.price)
                    book.timestamp = time.time()
                    book.seq = data.get("seq", book.seq)
                    self._books[symbol] = book
                    cb = self._book_callbacks.get(symbol)
                    if cb:
                        cb(book)
        except Exception:
            pass

    def get_cached_book(self, symbol: str) -> Optional[BybitOrderBook]:
        return self._books.get(symbol)

    def get_cached_funding(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._funding_cache.get(symbol)
