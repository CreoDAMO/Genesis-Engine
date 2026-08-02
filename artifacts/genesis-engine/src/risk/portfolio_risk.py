"""
Genesis Engine — Portfolio Risk Engine
Real-time CVaR, correlation monitoring, drawdown circuit breakers.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

import numpy as np


@dataclass
class RiskState:
    portfolio_value: float
    daily_pnl: float
    max_drawdown: float
    cvar_95: float
    correlation_risk: float
    circuit_breaker: bool
    timestamp: float


class PortfolioRiskEngine:
    """
    Monitors portfolio-level risk and triggers circuit breakers.
    """

    def __init__(self,
                 max_drawdown_pct: float = 0.15,
                 daily_loss_limit_usd: float = 5000.0,
                 cvar_window: int = 100,
                 correlation_window: int = 50):
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_limit_usd = daily_loss_limit_usd
        self.cvar_window = cvar_window
        self.correlation_window = correlation_window

        self._pnl_history: Deque[float] = deque(maxlen=cvar_window)
        self._value_history: Deque[float] = deque(maxlen=cvar_window)
        self._strategy_returns: Dict[str, Deque[float]] = {}
        self._peak_value = 0.0
        self._daily_start_value = 0.0
        self._last_reset_day = 0.0
        self._circuit_breaker = False

    def on_portfolio_update(self, value: float, strategy_pnls: Dict[str, float]):
        now = time.time()
        day = now // 86400

        if day != self._last_reset_day:
            self._daily_start_value = value
            self._last_reset_day = day

        self._value_history.append(value)
        if value > self._peak_value:
            self._peak_value = value

        # Update strategy return series
        for strat, pnl in strategy_pnls.items():
            if strat not in self._strategy_returns:
                self._strategy_returns[strat] = deque(maxlen=self.correlation_window)
            self._strategy_returns[strat].append(pnl)

        # Portfolio return
        if len(self._value_history) > 1:
            ret = (value - self._value_history[-2]) / self._value_history[-2]
            self._pnl_history.append(ret)

    def check_circuit_breaker(self) -> bool:
        if self._circuit_breaker:
            return True

        if not self._value_history:
            return False

        current = self._value_history[-1]
        dd = (self._peak_value - current) / self._peak_value if self._peak_value > 0 else 0.0
        daily_pnl = current - self._daily_start_value

        if dd > self.max_drawdown_pct:
            self._circuit_breaker = True
            return True

        if daily_pnl < -self.daily_loss_limit_usd:
            self._circuit_breaker = True
            return True

        return False

    def reset_circuit_breaker(self):
        self._circuit_breaker = False
        self._peak_value = self._value_history[-1] if self._value_history else 0.0

    def cvar(self, confidence: float = 0.95) -> float:
        if len(self._pnl_history) < 10:
            return 0.0
        returns = np.array(self._pnl_history)
        var = np.percentile(returns, (1 - confidence) * 100)
        cvar = returns[returns <= var].mean() if np.any(returns <= var) else var
        return float(cvar)

    def avg_correlation(self) -> float:
        """Average pairwise correlation across strategy return series."""
        series = [list(v) for v in self._strategy_returns.values() if len(v) > 5]
        if len(series) < 2:
            return 0.0
        min_len = min(len(s) for s in series)
        if min_len < 5:
            return 0.0
        arr = np.array([s[-min_len:] for s in series])
        corr_matrix = np.corrcoef(arr)
        mask = np.triu(np.ones_like(corr_matrix, dtype=bool), k=1)
        corrs = corr_matrix[mask]
        return float(np.mean(corrs)) if len(corrs) > 0 else 0.0

    def get_state(self) -> RiskState:
        current = self._value_history[-1] if self._value_history else 0.0
        dd = (self._peak_value - current) / self._peak_value if self._peak_value > 0 else 0.0
        return RiskState(
            portfolio_value=current,
            daily_pnl=current - self._daily_start_value,
            max_drawdown=dd,
            cvar_95=self.cvar(),
            correlation_risk=self.avg_correlation(),
            circuit_breaker=self._circuit_breaker,
            timestamp=time.time(),
        )
