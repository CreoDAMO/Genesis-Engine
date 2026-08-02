"""
Genesis Engine — Position Manager
Tracks positions across all venues, enforces limits, computes exposures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

import numpy as np


@dataclass
class Position:
    venue: str
    symbol: str
    size: Decimal          # Positive = long, Negative = short
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    margin_used: Decimal
    funding_paid: Decimal = Decimal("0")


class PositionManager:
    """
    Central position book for multi-venue, multi-asset portfolio.
    """

    def __init__(self, max_portfolio_exposure: float = 100000.0,
                 max_position_size: float = 20000.0,
                 max_leverage: float = 3.0):
        self.max_portfolio_exposure = max_portfolio_exposure
        self.max_position_size = max_position_size
        self.max_leverage = max_leverage
        self._positions: Dict[str, Position] = {}  # key = "venue:symbol"
        self._margin_used = Decimal("0")
        self._cash = Decimal("100000")  # Starting capital

    def update_position(self, pos: Position):
        key = f"{pos.venue}:{pos.symbol}"
        self._positions[key] = pos

    def get_position(self, venue: str, symbol: str) -> Decimal:
        key = f"{venue}:{symbol}"
        pos = self._positions.get(key)
        return pos.size if pos else Decimal("0")

    def get_position_obj(self, venue: str, symbol: str) -> Optional[Position]:
        return self._positions.get(f"{venue}:{symbol}")

    def all_positions(self) -> List[Position]:
        return list(self._positions.values())

    def total_exposure_usd(self) -> float:
        """Sum of absolute notional exposures."""
        return sum(
            abs(float(p.size) * float(p.mark_price))
            for p in self._positions.values()
        )

    def net_exposure_usd(self) -> float:
        """Net exposure (long - short) per asset, then sum absolute."""
        by_asset: Dict[str, float] = {}
        for p in self._positions.values():
            asset = p.symbol.replace("USDT", "").replace("USD", "").replace("-PERP", "")
            notional = float(p.size) * float(p.mark_price)
            by_asset[asset] = by_asset.get(asset, 0.0) + notional
        return sum(abs(v) for v in by_asset.values())

    def gross_pnl(self) -> float:
        return sum(float(p.unrealized_pnl) for p in self._positions.values())

    def margin_ratio(self) -> float:
        total_notional = self.total_exposure_usd()
        if total_notional == 0:
            return 0.0
        return float(self._margin_used) / total_notional

    def can_increase(self, venue: str, symbol: str, additional_usd: float) -> bool:
        """Check if adding this notional stays within limits."""
        new_exposure = self.total_exposure_usd() + abs(additional_usd)
        if new_exposure > self.max_portfolio_exposure:
            return False
        current = float(self.get_position(venue, symbol)) * 1.0  # rough price
        if abs(current + additional_usd) > self.max_position_size:
            return False
        return True
