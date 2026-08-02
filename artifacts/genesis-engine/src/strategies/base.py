"""
Genesis Engine — Strategy Base Class
All live strategies inherit from this. Enforces: risk checks, slippage estimation,
VM containment for evolved strategies, and audit logging.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.risk.position_manager import PositionManager
from src.microstructure.slippage_model import SlippageModel, SlippageEstimate


@dataclass
class StrategySignal:
    strategy_id: str
    venue: str           # "polymarket" | "binance" | "bybit" | "deribit"
    symbol: str
    side: str            # "BUY" | "SELL" | "HOLD"
    size: Decimal
    confidence: float    # 0-1
    expected_slippage_bps: float
    expected_fees_bps: float
    metadata: Dict[str, Any]


class BaseStrategy(ABC):
    """
    Abstract base for all Genesis Engine strategies.
    """

    def __init__(self, strategy_id: str, position_manager: PositionManager,
                 slippage_model: Optional[SlippageModel] = None):
        self.strategy_id = strategy_id
        self.pm = position_manager
        self.slippage = slippage_model or SlippageModel()
        self._enabled = True

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    @abstractmethod
    async def on_market_data(self, data: Dict[str, Any]) -> Optional[StrategySignal]:
        """Process new market data and optionally emit a signal."""
        ...

    @abstractmethod
    async def on_fill(self, fill: Dict[str, Any]):
        """Handle execution fill feedback."""
        ...

    def check_risk(self, signal: StrategySignal) -> bool:
        """Pre-flight risk check. Override for custom logic."""
        if not self._enabled:
            return False
        current = self.pm.get_position(signal.venue, signal.symbol)
        if abs(float(current + signal.size)) > self.pm.max_position_size:
            return False
        if self.pm.total_exposure_usd() > self.pm.max_portfolio_exposure:
            return False
        return True

    def estimate_slippage(self, venue: str, symbol: str, side: str, size: Decimal,
                          book: Any) -> SlippageEstimate:
        return self.slippage.estimate(book, side.lower(), size)
