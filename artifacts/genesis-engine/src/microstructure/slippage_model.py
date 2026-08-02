"""
Genesis Engine — Slippage Model
Estimates execution slippage from L2 order book depth.
Supports: linear interpolation, power-law depth model, and empirical calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple

import numpy as np

from .orderbook import UnifiedOrderBook


@dataclass
class SlippageEstimate:
    side: str  # "buy" | "sell"
    size: Decimal
    expected_price: Decimal
    slippage_bps: float
    market_impact_bps: float
    confidence: float  # 0-1 based on book depth adequacy
    filled_levels: int


class SlippageModel:
    """
    Estimate execution slippage from order book depth.

    Models:
      1. Naive: walk the book
      2. Power-law: assume depth follows power law beyond visible levels
      3. Calibrated: use historical fill data to fit venue-specific params
    """

    def __init__(self, model_type: str = "naive", power_law_exp: float = -1.5):
        self.model_type = model_type
        self.power_law_exp = power_law_exp
        self._calibration: dict = {}

    def estimate(
        self,
        book: UnifiedOrderBook,
        side: str,
        size: Decimal,
        max_levels: int = 20,
    ) -> SlippageEstimate:
        """
        Estimate slippage for an order of given size.
        side: "buy" (taking asks) or "sell" (hitting bids)
        """
        levels = book.asks if side == "buy" else book.bids
        if not levels:
            return SlippageEstimate(
                side=side, size=size, expected_price=Decimal("0"),
                slippage_bps=0.0, market_impact_bps=0.0,
                confidence=0.0, filled_levels=0,
            )

        mid = book.mid()
        if mid is None or mid == 0:
            mid = levels[0].price

        remaining = float(size)
        notional_filled = 0.0
        avg_price = 0.0
        filled_levels = 0

        for level in levels[:max_levels]:
            if remaining <= 0:
                break
            level_size = float(level.size)
            take = min(remaining, level_size)
            notional_filled += take * float(level.price)
            remaining -= take
            filled_levels += 1

        # If we exhausted visible book, apply power-law extrapolation
        if remaining > 0 and self.model_type == "power_law" and levels:
            last_price = float(levels[min(filled_levels, len(levels) - 1)].price)
            last_size = float(levels[min(filled_levels, len(levels) - 1)].size)
            # Extrapolate additional depth
            extra_notional = self._extrapolate_depth(
                remaining, last_price, last_size
            )
            notional_filled += extra_notional
            remaining = 0  # Assume filled via extrapolation

        if float(size) > 0:
            avg_price = Decimal(str(notional_filled / float(size)))
        else:
            avg_price = levels[0].price

        # Slippage vs mid
        if side == "buy":
            slippage = (avg_price - mid) / mid if mid > 0 else Decimal("0")
        else:
            slippage = (mid - avg_price) / mid if mid > 0 else Decimal("0")

        slippage_bps = float(slippage) * 10000

        # Market impact: slippage relative to best price
        best = levels[0].price
        if side == "buy":
            impact = (avg_price - best) / best if best > 0 else Decimal("0")
        else:
            impact = (best - avg_price) / best if best > 0 else Decimal("0")

        impact_bps = float(impact) * 10000

        # Confidence based on how much of order was filled from visible book
        visible_fill = 1.0 - (remaining / float(size)) if float(size) > 0 else 0.0
        confidence = min(1.0, visible_fill)

        return SlippageEstimate(
            side=side,
            size=size,
            expected_price=avg_price,
            slippage_bps=slippage_bps,
            market_impact_bps=impact_bps,
            confidence=confidence,
            filled_levels=filled_levels,
        )

    def _extrapolate_depth(self, remaining: float, last_price: float, last_size: float) -> float:
        """Power-law extrapolation of book depth beyond visible levels."""
        # Simplified: assume each additional level has size = last_size * (level_idx ^ exp)
        extra_notional = 0.0
        level_idx = 1
        while remaining > 0 and level_idx < 100:
            extrapolated_size = last_size * (level_idx ** self.power_law_exp)
            if extrapolated_size <= 0:
                break
            take = min(remaining, extrapolated_size)
            # Price moves linearly away from last price (simplified)
            price = last_price * (1 + 0.0001 * level_idx)
            extra_notional += take * price
            remaining -= take
            level_idx += 1
        return extra_notional

    def calibrate(self, fills: List[Tuple[Decimal, Decimal, Decimal, str]]):
        """
        Calibrate model using historical fill data.
        fills: [(expected_size, actual_price, predicted_price, side), ...]
        """
        errors = []
        for expected_size, actual, predicted, side in fills:
            if predicted > 0:
                err = float((actual - predicted) / predicted)
                errors.append(err)
        if errors:
            self._calibration["bias"] = float(np.mean(errors))
            self._calibration["rmse"] = float(np.sqrt(np.mean(np.square(errors))))
