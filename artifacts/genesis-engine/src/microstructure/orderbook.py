"""
Genesis Engine — Unified Order Book & Market Microstructure
Aggregates L2 data from Polymarket + CEX venues into a unified view.
Computes real-time microstructure features: spread, imbalance, VPIN, etc.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from collections import deque

import numpy as np


@dataclass
class UnifiedBookLevel:
    price: Decimal
    size: Decimal
    venue: str


@dataclass
class UnifiedOrderBook:
    symbol: str  # e.g. "BTC-PERP" or "0xabc..."
    bids: List[UnifiedBookLevel] = field(default_factory=list)
    asks: List[UnifiedBookLevel] = field(default_factory=list)
    timestamp: float = 0.0
    venue: str = ""

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

    def spread(self) -> Optional[Decimal]:
        bb = self.best_bid()
        ba = self.best_ask()
        if bb and ba:
            return ba - bb
        return None

    def spread_bps(self) -> Optional[float]:
        sp = self.spread()
        mid = self.mid()
        if sp and mid and mid > 0:
            return float(sp / mid) * 10000
        return None

    def imbalance(self) -> float:
        bid_vol = sum(float(l.size) for l in self.bids)
        ask_vol = sum(float(l.size) for l in self.asks)
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    def depth(self, levels: int = 5) -> Tuple[float, float]:
        """Return (bid_depth, ask_depth) in notional terms."""
        bid_depth = sum(float(l.price * l.size) for l in self.bids[:levels])
        ask_depth = sum(float(l.price * l.size) for l in self.asks[:levels])
        return bid_depth, ask_depth

    def weighted_mid(self) -> Optional[Decimal]:
        """Volume-weighted mid price."""
        if not self.bids or not self.asks:
            return None
        bb, ba = self.bids[0], self.asks[0]
        total = bb.size + ba.size
        if total == 0:
            return None
        return (bb.price * ba.size + ba.price * bb.size) / total


class MicrostructureEngine:
    """
    Real-time microstructure feature extraction.
    Maintains rolling windows for VPIN, order flow, and toxicity metrics.
    """

    def __init__(
        self,
        symbol: str,
        window_size: int = 100,
        vpin_buckets: int = 50,
        trade_lookback: int = 1000,
    ):
        self.symbol = symbol
        self.window_size = window_size
        self.vpin_buckets = vpin_buckets
        self.trade_lookback = trade_lookback

        self._mids: deque = deque(maxlen=window_size)
        self._spreads: deque = deque(maxlen=window_size)
        self._imbalances: deque = deque(maxlen=window_size)
        self._trades: deque = deque(maxlen=trade_lookback)  # (timestamp, price, size, side)
        self._returns: deque = deque(maxlen=window_size)
        self._book_updates: int = 0
        self._last_mid: Optional[Decimal] = None

    def on_book_update(self, book: UnifiedOrderBook):
        """Process a new order book snapshot."""
        mid = book.mid()
        if mid is None:
            return

        self._mids.append(float(mid))
        sp = book.spread()
        if sp is not None:
            self._spreads.append(float(sp))
        self._imbalances.append(book.imbalance())
        self._book_updates += 1

        if self._last_mid is not None:
            ret = float((mid - self._last_mid) / self._last_mid) if self._last_mid > 0 else 0.0
            self._returns.append(ret)
        self._last_mid = mid

    def on_trade(self, price: Decimal, size: Decimal, side: str):
        """Process a trade tick."""
        self._trades.append((time.time(), float(price), float(size), side))

    # ------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------

    def spread(self) -> Optional[float]:
        return self._spreads[-1] if self._spreads else None

    def avg_spread(self) -> Optional[float]:
        return float(np.mean(self._spreads)) if len(self._spreads) > 0 else None

    def imbalance(self) -> Optional[float]:
        return self._imbalances[-1] if self._imbalances else None

    def avg_imbalance(self) -> Optional[float]:
        return float(np.mean(self._imbalances)) if len(self._imbalances) > 0 else None

    def volatility(self) -> float:
        if len(self._returns) < 2:
            return 0.0
        return float(np.std(self._returns) * np.sqrt(len(self._returns)))

    def realized_vol(self) -> float:
        if len(self._returns) < 2:
            return 0.0
        return float(np.sqrt(np.sum(np.square(self._returns))))

    def vpin(self) -> float:
        """
        Volume-Synchronized Probability of Informed Trading (simplified).
        Measures toxicity of order flow.
        """
        if len(self._trades) < self.vpin_buckets:
            return 0.0

        # Bucket trades by volume
        total_vol = sum(t[2] for t in self._trades)
        bucket_vol = total_vol / self.vpin_buckets

        buckets = []
        current_bucket = []
        current_vol = 0.0

        for _, price, size, side in self._trades:
            current_bucket.append((price, size, side))
            current_vol += size
            if current_vol >= bucket_vol:
                buckets.append(current_bucket)
                current_bucket = []
                current_vol = 0.0

        if current_bucket:
            buckets.append(current_bucket)

        if len(buckets) < 2:
            return 0.0

        # VPIN = mean |buy_vol - sell_vol| / total_vol per bucket
        vpin_values = []
        for bucket in buckets:
            buy_vol = sum(size for _, size, side in bucket if side == "buy")
            sell_vol = sum(size for _, size, side in bucket if side == "sell")
            total = buy_vol + sell_vol
            if total > 0:
                vpin_values.append(abs(buy_vol - sell_vol) / total)

        return float(np.mean(vpin_values)) if vpin_values else 0.0

    def order_flow_imbalance(self, lookback: int = 50) -> float:
        """OFI: net buyer-initiated minus seller-initiated volume."""
        recent = list(self._trades)[-lookback:]
        if not recent:
            return 0.0
        buy_vol = sum(size for _, _, size, side in recent if side == "buy")
        sell_vol = sum(size for _, _, size, side in recent if side == "sell")
        total = buy_vol + sell_vol
        if total == 0:
            return 0.0
        return (buy_vol - sell_vol) / total

    def trade_intensity(self) -> float:
        """Trades per second over lookback window."""
        if len(self._trades) < 2:
            return 0.0
        recent = list(self._trades)
        dt = recent[-1][0] - recent[0][0]
        if dt <= 0:
            return 0.0
        return len(recent) / dt

    def feature_vector(self) -> Dict[str, float]:
        """Current microstructure feature snapshot."""
        return {
            "spread": self.spread() or 0.0,
            "avg_spread": self.avg_spread() or 0.0,
            "imbalance": self.imbalance() or 0.0,
            "avg_imbalance": self.avg_imbalance() or 0.0,
            "volatility": self.volatility(),
            "realized_vol": self.realized_vol(),
            "vpin": self.vpin(),
            "ofi": self.order_flow_imbalance(),
            "trade_intensity": self.trade_intensity(),
            "book_updates": float(self._book_updates),
        }
