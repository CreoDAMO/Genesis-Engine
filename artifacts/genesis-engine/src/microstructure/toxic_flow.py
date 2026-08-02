"""
Genesis Engine — Toxic Flow Detector
Classifies order flow as toxic (informed) vs benign (uninformed) using:
  - VPIN (Volume-Synchronized Probability of Informed Trading)
  - Order flow imbalance
  - Trade-size distribution (Kyle's lambda proxy)
  - Adverse selection metrics
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque

import numpy as np


@dataclass
class ToxicitySignal:
    symbol: str
    timestamp: float
    vpin: float
    ofi: float
    kyle_lambda: float
    adverse_selection: float
    toxicity_score: float  # 0-1 composite
    is_toxic: bool
    confidence: float


class ToxicFlowDetector:
    """
    Detects toxic (informed) order flow in real-time.

    Toxic flow indicators:
      1. High VPIN → informed traders are active
      2. Extreme OFI → one-sided pressure
      3. High Kyle's lambda → price impact per unit volume is high
      4. Adverse selection: trades predict future price moves
    """

    def __init__(
        self,
        symbol: str,
        vpin_window: int = 50,
        ofi_threshold: float = 0.7,
        vpin_threshold: float = 0.6,
        lambda_threshold: float = 0.5,
        adverse_threshold: float = 0.5,
    ):
        self.symbol = symbol
        self.vpin_window = vpin_window
        self.ofi_threshold = ofi_threshold
        self.vpin_threshold = vpin_threshold
        self.lambda_threshold = lambda_threshold
        self.adverse_threshold = adverse_threshold

        self._trades: Deque[Tuple[float, float, float, str]] = deque(maxlen=1000)
        self._returns: Deque[float] = deque(maxlen=100)
        self._prices: Deque[float] = deque(maxlen=100)
        self._last_signal: Optional[ToxicitySignal] = None

    def on_trade(self, price: float, size: float, side: str, timestamp: float):
        """Ingest a trade tick."""
        self._trades.append((timestamp, price, size, side))
        self._prices.append(price)
        if len(self._prices) > 1:
            ret = (price - self._prices[-2]) / self._prices[-2] if self._prices[-2] > 0 else 0.0
            self._returns.append(ret)

    def on_book_imbalance(self, imbalance: float):
        """Ingest current book imbalance [-1, 1]."""
        self._last_imbalance = imbalance

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _compute_vpin(self) -> float:
        if len(self._trades) < self.vpin_window:
            return 0.0
        total_vol = sum(t[2] for t in self._trades)
        bucket_vol = total_vol / self.vpin_window
        buckets = []
        current = []
        cv = 0.0
        for _, _, size, side in self._trades:
            current.append((size, side))
            cv += size
            if cv >= bucket_vol:
                buy_vol = sum(s for s, sd in current if sd == "buy")
                sell_vol = sum(s for s, sd in current if sd == "sell")
                total = buy_vol + sell_vol
                if total > 0:
                    buckets.append(abs(buy_vol - sell_vol) / total)
                current = []
                cv = 0.0
        if current:
            buy_vol = sum(s for s, sd in current if sd == "buy")
            sell_vol = sum(s for s, sd in current if sd == "sell")
            total = buy_vol + sell_vol
            if total > 0:
                buckets.append(abs(buy_vol - sell_vol) / total)
        return float(np.mean(buckets)) if buckets else 0.0

    def _compute_ofi(self) -> float:
        if len(self._trades) < 10:
            return 0.0
        recent = list(self._trades)[-100:]
        buy_vol = sum(size for _, _, size, side in recent if side == "buy")
        sell_vol = sum(size for _, _, size, side in recent if side == "sell")
        total = buy_vol + sell_vol
        if total == 0:
            return 0.0
        return (buy_vol - sell_vol) / total

    def _compute_kyle_lambda(self) -> float:
        """
        Kyle's lambda: price change / signed volume.
        High lambda = high price impact per unit flow = toxic.
        """
        if len(self._trades) < 20 or len(self._returns) < 2:
            return 0.0
        # Signed volume over recent window
        recent = list(self._trades)[-50:]
        signed_vol = sum(
            size if side == "buy" else -size
            for _, _, size, side in recent
        )
        recent_return = self._returns[-1] if self._returns else 0.0
        if abs(signed_vol) < 1e-9:
            return 0.0
        return abs(recent_return / signed_vol)

    def _compute_adverse_selection(self) -> float:
        """
        Correlation between trade direction and future returns.
        High correlation = trades are informed (toxic).
        """
        if len(self._trades) < 50 or len(self._returns) < 10:
            return 0.0
        # Match trade signs with subsequent returns
        trade_signs = []
        future_rets = []
        trades_list = list(self._trades)
        returns_list = list(self._returns)
        for i in range(min(len(trades_list) - 1, len(returns_list) - 1)):
            sign = 1.0 if trades_list[i][3] == "buy" else -1.0
            trade_signs.append(sign)
            future_rets.append(returns_list[i])
        if len(trade_signs) < 10:
            return 0.0
        corr = np.corrcoef(trade_signs, future_rets)[0, 1]
        return float(abs(corr)) if np.isfinite(corr) else 0.0

    # ------------------------------------------------------------------
    # Composite signal
    # ------------------------------------------------------------------

    def detect(self) -> ToxicitySignal:
        """Run full toxicity analysis and return composite signal."""
        vpin = self._compute_vpin()
        ofi = self._compute_ofi()
        kyle = self._compute_kyle_lambda()
        adverse = self._compute_adverse_selection()

        # Normalize metrics to [0,1] using sigmoid-ish transforms
        vpin_norm = min(1.0, vpin)
        ofi_norm = abs(ofi)
        kyle_norm = min(1.0, kyle * 1000)  # Scale factor
        adverse_norm = adverse

        # Weighted composite
        weights = {"vpin": 0.3, "ofi": 0.25, "kyle": 0.25, "adverse": 0.2}
        score = (
            weights["vpin"] * vpin_norm
            + weights["ofi"] * ofi_norm
            + weights["kyle"] * kyle_norm
            + weights["adverse"] * adverse_norm
        )

        # Threshold-based classification
        is_toxic = (
            vpin_norm > self.vpin_threshold
            or ofi_norm > self.ofi_threshold
            or kyle_norm > self.lambda_threshold
            or adverse_norm > self.adverse_threshold
        )

        # Confidence based on data sufficiency
        confidence = min(1.0, len(self._trades) / 500)

        signal = ToxicitySignal(
            symbol=self.symbol,
            timestamp=time_module.time(),
            vpin=vpin,
            ofi=ofi,
            kyle_lambda=kyle,
            adverse_selection=adverse,
            toxicity_score=score,
            is_toxic=is_toxic,
            confidence=confidence,
        )
        self._last_signal = signal
        return signal
