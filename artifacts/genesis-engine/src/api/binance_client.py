"""
Genesis Engine — Binance USD-M Futures Client
Async REST + WebSocket for perp funding, order book, positions, and hedging.
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
from urllib.parse import urlencode

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed


@dataclass
class BinanceBookLevel:
    price: Decimal
    size: Decimal


@dataclass
class BinanceOrderBook:
    symbol: str
    bids: List[BinanceBookLevel] = field(default_factory=list)
    asks: List[BinanceBookLevel] = field(default_factory=list)
    timestamp: float = 0.0
    last_update_id: int = 0

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


class BinanceClient:
    """
    Binance USD-M Futures async client.
    Supports: funding rates, perp order books, positions, orders.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://fapi.binance.com",
        ws_url: str = "wss://fstream.binance.com/ws",
        testnet: bool = False,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.timeout = timeout

        if testnet:
            self.base_url = "https://testnet.binancefuture.com"
            self.ws_url = "wss://stream.binancefuture.com/ws"
        else:
            self.base_url = base_url.rstrip("/")
            self.ws_url = ws_url

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        self._reconnect_delay = 5.0

        self._books: Dict[str, BinanceOrderBook] = {}
        self._book_callbacks: Dict[str, Callable[[BinanceOrderBook], None]] = {}
        self._funding_cache: Dict[str, Dict[str, Any]] = {}

    async def start(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"X-MBX-APIKEY": self.api_key},
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

    def _sign(self, params: Dict[str, Any]) -> str:
        query = urlencode(params)
        return hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()

    # ------------------------------------------------------------------
    # REST — Public
    # ------------------------------------------------------------------

    async def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """Current funding rate for a perp."""
        url = f"{self.base_url}/fapi/v1/fundingRate?symbol={symbol}&limit=1"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if data:
                self._funding_cache[symbol] = data[0]
            return data[0] if data else {}

    async def get_all_funding_rates(self) -> List[Dict[str, Any]]:
        """All perp funding rates."""
        url = f"{self.base_url}/fapi/v1/premiumIndex"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            for d in data:
                self._funding_cache[d.get("symbol", "")] = d
            return data

    async def get_order_book(self, symbol: str, limit: int = 100) -> BinanceOrderBook:
        """L2 order book snapshot."""
        url = f"{self.base_url}/fapi/v1/depth?symbol={symbol}&limit={limit}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            bids = [BinanceBookLevel(Decimal(b[0]), Decimal(b[1])) for b in data.get("bids", [])]
            asks = [BinanceBookLevel(Decimal(a[0]), Decimal(a[1])) for a in data.get("asks", [])]
            book = BinanceOrderBook(
                symbol=symbol,
                bids=sorted(bids, key=lambda x: x.price, reverse=True),
                asks=sorted(asks, key=lambda x: x.price),
                timestamp=time.time(),
                last_update_id=data.get("lastUpdateId", 0),
            )
            self._books[symbol] = book
            return book

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        url = f"{self.base_url}/fapi/v1/ticker/24hr?symbol={symbol}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[List]:
        url = f"{self.base_url}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # REST — Private
    # ------------------------------------------------------------------

    async def get_account(self) -> Dict[str, Any]:
        ts = int(time.time() * 1000)
        params = {"timestamp": ts}
        params["signature"] = self._sign(params)
        url = f"{self.base_url}/fapi/v2/account?{urlencode(params)}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_positions(self) -> List[Dict[str, Any]]:
        ts = int(time.time() * 1000)
        params = {"timestamp": ts}
        params["signature"] = self._sign(params)
        url = f"{self.base_url}/fapi/v2/positionRisk?{urlencode(params)}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def place_order(
        self,
        symbol: str,
        side: str,  # BUY / SELL
        order_type: str,  # MARKET / LIMIT
        quantity: Decimal,
        price: Optional[Decimal] = None,
        time_in_force: str = "GTC",
    ) -> Dict[str, Any]:
        ts = int(time.time() * 1000)
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": str(quantity),
            "timestamp": ts,
        }
        if order_type == "LIMIT":
            params["price"] = str(price)
            params["timeInForce"] = time_in_force
        params["signature"] = self._sign(params)
        url = f"{self.base_url}/fapi/v1/order"
        async with self._session.post(url, data=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        ts = int(time.time() * 1000)
        params = {"symbol": symbol, "orderId": order_id, "timestamp": ts}
        params["signature"] = self._sign(params)
        url = f"{self.base_url}/fapi/v1/order?{urlencode(params)}"
        async with self._session.delete(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # WebSocket — Order Book @100ms
    # ------------------------------------------------------------------

    async def subscribe_book(self, symbol: str, callback: Callable[[BinanceOrderBook], None]):
        """Subscribe to real-time depth stream."""
        self._book_callbacks[symbol.lower()] = callback
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self):
        while self._running:
            try:
                streams = "/".join(f"{s}@depth@100ms" for s in self._book_callbacks)
                uri = f"{self.ws_url}/stream?streams={streams}"
                async with websockets.connect(uri) as ws:
                    self._ws = ws
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
            stream = msg.get("stream", "")
            data = msg.get("data", {})
            symbol = stream.replace("@depth@100ms", "").upper()
            if symbol in self._book_callbacks:
                book = self._books.get(symbol, BinanceOrderBook(symbol=symbol))
                self._apply_delta(book, data)
                book.timestamp = time.time()
                self._books[symbol] = book
                cb = self._book_callbacks.get(symbol)
                if cb:
                    cb(book)
        except Exception:
            pass

    def _apply_delta(self, book: BinanceOrderBook, data: Dict[str, Any]):
        for b in data.get("b", []):
            price, qty = Decimal(b[0]), Decimal(b[1])
            book.bids = [l for l in book.bids if l.price != price]
            if qty > 0:
                book.bids.append(BinanceBookLevel(price, qty))
        book.bids.sort(key=lambda x: x.price, reverse=True)
        for a in data.get("a", []):
            price, qty = Decimal(a[0]), Decimal(a[1])
            book.asks = [l for l in book.asks if l.price != price]
            if qty > 0:
                book.asks.append(BinanceBookLevel(price, qty))
        book.asks.sort(key=lambda x: x.price)

    def get_cached_book(self, symbol: str) -> Optional[BinanceOrderBook]:
        return self._books.get(symbol.upper())

    def get_cached_funding(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._funding_cache.get(symbol.upper())
