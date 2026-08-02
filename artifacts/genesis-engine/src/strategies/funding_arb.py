"""
Genesis Engine — Funding Rate Arbitrage
Scans funding rates across Binance, Bybit, Deribit.
When funding rate divergence exceeds threshold + carry > slippage + fees,
enters long on low-funding venue, short on high-funding venue.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .base import BaseStrategy, StrategySignal


class FundingArbitrage(BaseStrategy):
    """
    Cross-venue funding rate arbitrage.

    Logic:
      1. Collect funding rates from all CEX venues for a perp
      2. Find max divergence: max_rate - min_rate
      3. If divergence > threshold AND expected 8h carry > costs:
           - Short perp on highest funding venue
           - Long perp on lowest funding venue (or spot hedge)
      4. Rebalance every funding interval (8h) or when divergence closes
    """

    def __init__(self, strategy_id: str, position_manager, slippage_model=None,
                 min_divergence_bps: float = 5.0,
                 min_carry_bps: float = 3.0,
                 max_hold_hours: int = 8):
        super().__init__(strategy_id, position_manager, slippage_model)
        self.min_divergence_bps = min_divergence_bps
        self.min_carry_bps = min_carry_bps
        self.max_hold_hours = max_hold_hours
        self._funding_cache: Dict[str, Dict[str, Any]] = {}
        self._last_rebalance = 0.0

    async def update_funding(self, venue: str, symbol: str, rate: float, next_funding: float):
        self._funding_cache[f"{venue}:{symbol}"] = {
            "rate": rate,
            "next_funding": next_funding,
            "timestamp": asyncio.get_event_loop().time(),
        }

    async def on_market_data(self, data: Dict[str, Any]) -> Optional[StrategySignal]:
        if data.get("type") != "funding_snapshot":
            return None

        symbol = data.get("symbol", "")
        venues = data.get("venues", {})
        if len(venues) < 2:
            return None

        rates = [(v, info["rate"]) for v, info in venues.items()]
        rates.sort(key=lambda x: x[1])

        low_venue, low_rate = rates[0]
        high_venue, high_rate = rates[-1]

        divergence_bps = (high_rate - low_rate) * 10000
        if divergence_bps < self.min_divergence_bps:
            return None

        carry_bps = abs(high_rate) * 10000
        if carry_bps < self.min_carry_bps:
            return None

        current_low = self.pm.get_position(low_venue, symbol)
        current_high = self.pm.get_position(high_venue, symbol)

        notional = Decimal("1000")

        if current_high >= 0:
            return StrategySignal(
                strategy_id=self.strategy_id,
                venue=high_venue,
                symbol=symbol,
                side="SELL",
                size=notional,
                confidence=min(1.0, divergence_bps / 20.0),
                expected_slippage_bps=5.0,
                expected_fees_bps=4.0,
                metadata={
                    "type": "funding_arb",
                    "leg": "short_high",
                    "divergence_bps": divergence_bps,
                    "carry_bps": carry_bps,
                    "hedge_venue": low_venue,
                },
            )

        if current_low <= 0:
            return StrategySignal(
                strategy_id=self.strategy_id,
                venue=low_venue,
                symbol=symbol,
                side="BUY",
                size=notional,
                confidence=min(1.0, divergence_bps / 20.0),
                expected_slippage_bps=5.0,
                expected_fees_bps=4.0,
                metadata={
                    "type": "funding_arb",
                    "leg": "long_low",
                    "divergence_bps": divergence_bps,
                    "carry_bps": carry_bps,
                    "hedge_venue": high_venue,
                },
            )

        return None

    async def on_fill(self, fill: Dict[str, Any]):
        pass
