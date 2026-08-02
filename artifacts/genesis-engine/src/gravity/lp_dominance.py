"""
gravity/lp_dominance.py

Polymarket CLOB market making with inventory-aware quoting.
The 'gravity': tight spreads + deep size = price discovery flows to you.

Integrates with:
  - reality_surface for fair probability consensus
  - perp_hedge for cross-venue inventory management
  - polymarket_client for order placement
"""

from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Dict, List, Callable
from collections import deque
import numpy as np

logger = logging.getLogger("gravity")


@dataclass
class Quote:
    """A single-sided quote."""
    side: str           # "bid" or "ask"
    price: float        # [0.001, 0.999]
    size: float         # Number of shares
    market_id: str

    def __post_init__(self):
        self.price = float(np.clip(self.price, 0.001, 0.999))
        self.size = max(0.0, self.size)


@dataclass
class InventoryState:
    """Track net inventory across venues."""
    market_id: str
    pm_yes_shares: float = 0.0
    pm_usdc_locked: float = 0.0
    perp_delta: float = 0.0

    @property
    def net_delta(self) -> float:
        return self.pm_yes_shares + self.perp_delta

    @property
    def gross_exposure(self) -> float:
        return abs(self.pm_yes_shares) + abs(self.perp_delta)


class GravityMarketMaker:
    """
    Inventory-skewed market maker for Polymarket CLOB.

    Core idea:
    1. Compute fair probability from RealitySurface consensus
    2. Quote bid/ask around fair with dynamic spread
    3. Skew quotes away from inventory buildup
    4. Hedge excess inventory on perp venue automatically

    Args:
        polymarket_client: Your existing CLOB connector.
        reality_surface:   RealitySurface instance.
        perp_hedger:       async callback(market_id, side, size) → dict.
        target_spread:     Base spread as fraction (e.g. 0.02 = 2%).
        max_inventory:     Max net shares before emergency hedge.
        skew_factor:       Aggressiveness of inventory skew (0.5 = moderate).
        quote_size_base:   Base order size in shares.
        min_spread:        Minimum spread to prevent zero-width.
    """

    def __init__(
        self,
        polymarket_client,
        reality_surface,
        perp_hedger: Optional[Callable] = None,
        target_spread: float = 0.02,
        max_inventory: float = 5000.0,
        skew_factor: float = 0.5,
        quote_size_base: float = 100.0,
        min_spread: float = 0.005,
        emergency_hedge_threshold: float = 0.8,
    ):
        self.pm = polymarket_client
        self.surface = reality_surface
        self.perp_hedger = perp_hedger

        self.target_spread = target_spread
        self.max_inventory = max_inventory
        self.skew_factor = skew_factor
        self.quote_size_base = quote_size_base
        self.min_spread = min_spread
        self.emergency_hedge_threshold = emergency_hedge_threshold

        self.inventory: Dict[str, InventoryState] = {}
        self.active_orders: Dict[str, List[dict]] = {}
        self.trade_history: deque = deque(maxlen=10_000)
        self.realized_pnl: float = 0.0

        self.volatility_ewma: Dict[str, float] = {}
        self.vol_lambda: float = 0.94
        self._last_mid: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Core Quoting
    # ------------------------------------------------------------------

    def compute_quotes(self, market_id: str) -> Optional[Dict]:
        """
        Compute bid/ask quotes for a market.
        Returns {"bid": Quote, "ask": Quote, "fair": float, ...} or None.
        """
        fair_prob = self.surface.consensus_probability(market_id)
        if fair_prob is None:
            logger.warning(f"[{market_id}] No consensus probability — skipping quotes")
            return None

        inv = self.inventory.get(market_id, InventoryState(market_id=market_id))
        spread = self._dynamic_spread(market_id, fair_prob)
        skew = self._compute_skew(inv)

        half_spread = spread / 2.0
        bid = fair_prob * (1.0 - half_spread + skew)
        ask = fair_prob * (1.0 + half_spread + skew)

        # Enforce minimum spread
        if ask - bid < self.min_spread:
            mid = (bid + ask) / 2.0
            bid = mid - self.min_spread / 2.0
            ask = mid + self.min_spread / 2.0

        bid = float(np.clip(bid, 0.001, 0.999))
        ask = float(np.clip(ask, 0.001, 0.999))

        uncertainty = self.surface.consensus_uncertainty(market_id) or 0.1
        prob_penalty = 1.0 - abs(fair_prob - 0.5) * 2.0
        inv_ratio = abs(inv.net_delta) / max(self.max_inventory, 1)
        inv_penalty = max(0.0, 1.0 - inv_ratio ** 2)

        size = self.quote_size_base * (1.0 - uncertainty * 2) * prob_penalty * inv_penalty
        size = max(1.0, size)

        return {
            "bid": Quote(side="bid", price=bid, size=size, market_id=market_id),
            "ask": Quote(side="ask", price=ask, size=size, market_id=market_id),
            "fair": fair_prob,
            "spread": spread,
            "skew": skew,
        }

    def _dynamic_spread(self, market_id: str, fair_prob: float) -> float:
        base = self.target_spread
        jump_risk = abs(fair_prob - 0.5) * 2.0
        base *= 1.0 + jump_risk * 2.0
        vol = self.volatility_ewma.get(market_id, 0.01)
        base *= 1.0 + vol * 10.0
        return float(np.clip(base, self.min_spread, 0.15))

    def _compute_skew(self, inv: InventoryState) -> float:
        """Positive skew = raise prices (we're short). Negative = lower (we're long)."""
        if self.max_inventory <= 0:
            return 0.0
        ratio = inv.net_delta / self.max_inventory
        skew = -ratio * self.skew_factor
        return float(np.clip(skew, -0.5, 0.5))

    # ------------------------------------------------------------------
    # Order Management
    # ------------------------------------------------------------------

    async def refresh_quotes(self, market_id: str):
        """Cancel old quotes and place new ones. Call every 1–5 s per market."""
        quotes = self.compute_quotes(market_id)
        if quotes is None:
            await self._cancel_all(market_id)
            return

        await self._cancel_all(market_id)

        new_orders = []
        for side in ("bid", "ask"):
            q = quotes[side]
            try:
                order = await self.pm.place_order(
                    market_id=market_id,
                    side="BUY" if side == "bid" else "SELL",
                    price=q.price,
                    size=q.size,
                    order_type="GTC",
                )
                new_orders.append(order)
                logger.info(
                    f"[{market_id}] {side.upper()} @ {q.price:.4f} × {q.size:.1f} "
                    f"(fair={quotes['fair']:.4f}, spread={quotes['spread']:.3%}, "
                    f"skew={quotes['skew']:+.3f})"
                )
            except Exception as e:
                logger.error(f"[{market_id}] Failed to place {side}: {e}")

        self.active_orders[market_id] = new_orders

    async def _cancel_all(self, market_id: str):
        for order in self.active_orders.get(market_id, []):
            try:
                await self.pm.cancel_order(order_id=order.get("id"))
            except Exception:
                pass  # May already be filled
        self.active_orders[market_id] = []

    # ------------------------------------------------------------------
    # Fill Handling & Inventory
    # ------------------------------------------------------------------

    async def on_fill(self, fill_event: dict):
        """Process a fill from the Polymarket WebSocket."""
        market_id = fill_event["market_id"]
        side = fill_event["side"]
        size = fill_event["size"]
        price = fill_event["price"]

        if market_id not in self.inventory:
            self.inventory[market_id] = InventoryState(market_id=market_id)

        inv = self.inventory[market_id]

        if side == "BUY":
            inv.pm_yes_shares += size
            inv.pm_usdc_locked += size * price
        else:
            inv.pm_yes_shares -= size
            inv.pm_usdc_locked -= size * price

        self.trade_history.append({
            "timestamp": time.time(),
            "market_id": market_id,
            "side": side,
            "size": size,
            "price": price,
            "pnl": 0.0,
        })

        logger.info(
            f"[{market_id}] FILL {side} {size:.1f} @ {price:.4f} | "
            f"Net delta: {inv.net_delta:+.1f}"
        )

        await self._check_hedge(market_id)

    async def _check_hedge(self, market_id: str):
        inv = self.inventory.get(market_id)
        if not inv:
            return
        ratio = abs(inv.net_delta) / max(self.max_inventory, 1)
        if ratio >= self.emergency_hedge_threshold:
            logger.warning(
                f"[{market_id}] EMERGENCY HEDGE triggered: "
                f"{inv.net_delta:+.1f} / {self.max_inventory} ({ratio:.1%})"
            )
            await self._hedge_inventory(market_id)

    async def _hedge_inventory(self, market_id: str):
        if self.perp_hedger is None:
            logger.warning(f"[{market_id}] No perp hedger configured — inventory unhedged!")
            return

        inv = self.inventory[market_id]
        if inv.net_delta > 0:
            hedge_side, hedge_size = "SELL", inv.net_delta
        else:
            hedge_side, hedge_size = "BUY", -inv.net_delta

        try:
            await self.perp_hedger(market_id=market_id, side=hedge_side, size=hedge_size)
            if hedge_side == "BUY":
                inv.perp_delta += hedge_size
            else:
                inv.perp_delta -= hedge_size
            logger.info(
                f"[{market_id}] HEDGED {hedge_side} {hedge_size:.1f} on perp | "
                f"New net delta: {inv.net_delta:+.1f}"
            )
        except Exception as e:
            logger.error(f"[{market_id}] Hedge failed: {e}")

    # ------------------------------------------------------------------
    # Volatility
    # ------------------------------------------------------------------

    def update_volatility(self, market_id: str, mid_price: float):
        if market_id not in self.volatility_ewma:
            self.volatility_ewma[market_id] = 0.01
            self._last_mid[market_id] = mid_price
            return

        last = self._last_mid.get(market_id, mid_price)
        if last <= 0:
            return

        ret = (mid_price - last) / last
        old_vol = self.volatility_ewma[market_id]
        new_vol = float(np.sqrt(self.vol_lambda * old_vol ** 2 + (1 - self.vol_lambda) * ret ** 2))
        self.volatility_ewma[market_id] = new_vol
        self._last_mid[market_id] = mid_price

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "timestamp": time.time(),
            "n_markets": len(self.inventory),
            "total_net_delta": sum(abs(inv.net_delta) for inv in self.inventory.values()),
            "total_gross_exposure": sum(inv.gross_exposure for inv in self.inventory.values()),
            "n_active_orders": sum(len(o) for o in self.active_orders.values()),
            "n_trades": len(self.trade_history),
            "realized_pnl": self.realized_pnl,
            "markets": {
                mid: {
                    "net_delta": inv.net_delta,
                    "gross": inv.gross_exposure,
                    "pm_shares": inv.pm_yes_shares,
                    "perp_delta": inv.perp_delta,
                    "vol": self.volatility_ewma.get(mid, 0.01),
                }
                for mid, inv in self.inventory.items()
            },
        }
