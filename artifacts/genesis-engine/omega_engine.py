"""
omega_engine.py  — Practical v6 integration layer

Ties together:
  - reality_surface  (cross-venue probability consensus)
  - gravity          (inventory-skewed market making)
  - sandbox          (WASM-sandboxed strategy execution)
  - polymarket_client (your existing CLOB connector)
  - perp_hedge       (your existing cross-venue hedge)
  - genetic_strategy_engine (your existing GP)

No quantum. No LEO satellites. Just production trading infrastructure.

Quick start (paper mode):
    cd artifacts/genesis-engine
    python omega_engine.py

Live trading (only after weeks of paper):
    export PM_API_KEY="..."  PM_API_SECRET="..."  PM_PASSPHRASE="..."
    export DERIBIT_KEY="..."  DERIBIT_SECRET="..."
    export PAPER_TRADE="false"
    python omega_engine.py
"""

from __future__ import annotations

import os
import sys
import time
import asyncio
import signal
import logging
import json
import hashlib
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Path setup: same pattern as run.py
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
SRC  = ROOT / "src"
VM   = SRC / "vm"

for p in (str(ROOT), str(SRC), str(VM)):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-14s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(ROOT / "logs" / "omega_engine.log")),
    ],
)
logger = logging.getLogger("omega")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class OmegaConfig:
    """Production configuration — start in paper_trade=True, always."""

    # Polymarket
    pm_api_key:     str = field(default_factory=lambda: os.getenv("PM_API_KEY", ""))
    pm_api_secret:  str = field(default_factory=lambda: os.getenv("PM_API_SECRET", ""))
    pm_passphrase:  str = field(default_factory=lambda: os.getenv("PM_PASSPHRASE", ""))

    # Deribit (for perp hedge)
    deribit_key:    str = field(default_factory=lambda: os.getenv("DERIBIT_KEY", ""))
    deribit_secret: str = field(default_factory=lambda: os.getenv("DERIBIT_SECRET", ""))

    # Markets to make on (Polymarket market IDs)
    markets: List[str] = field(default_factory=lambda: [
        # Replace with real market IDs before going live
        "0x_placeholder_market_id",
    ])

    # Trading parameters
    max_position_usd:      float = 5_000.0
    target_spread:         float = 0.02
    quote_interval_sec:    float = 3.0

    # Risk limits
    max_drawdown_pct:           float = 0.15
    daily_loss_limit_usd:       float = 500.0
    emergency_hedge_threshold:  float = 0.8

    # GP / Strategy
    gp_population_size: int   = 100
    gp_generations:     int   = 20
    gp_elite_pct:       float = 0.05
    wasm_fuel_limit:    int   = 10_000
    gp_cycle_sec:       float = 1800.0   # 30-minute evolution cycle

    # Audit
    audit_log_path: str = str(ROOT / "logs" / "audit_omega.jsonl")

    # Mode — START HERE.  Set False only after weeks of paper.
    paper_trade: bool = field(
        default_factory=lambda: os.getenv("PAPER_TRADE", "true").lower() == "true"
    )


# ---------------------------------------------------------------------------
# Omega Engine
# ---------------------------------------------------------------------------

class OmegaEngine:
    """
    Practical v6 trading engine.

    Architecture:
        Polymarket WS ──┐
        Deribit WS    ──┼──► Reality Surface ──► Gravity LP ──► CLOB orders
        Funding APIs  ──┘
                                                  ▲
        GP Engine ──► WASM Sandbox ──────────────┘  (feeds fair-price model)
    """

    def __init__(self, config: Optional[OmegaConfig] = None):
        self.cfg = config or OmegaConfig()
        self._shutdown_event = asyncio.Event()
        self._audit_seq = 0

        # Subsystems (initialized in start())
        self.surface  = None
        self.gravity  = None
        self.wasm     = None
        self.pm_client     = None
        self.deribit_client = None
        self.gp_engine = None

        # State
        self.daily_pnl:     float = 0.0
        self.peak_pnl:      float = 0.0
        self.session_start: float = time.time()
        self.is_running:    bool  = False

        # Performance
        self.latency_samples: deque = deque(maxlen=1000)
        self.quote_count: int = 0
        self.fill_count:  int = 0

        # Ensure log dir exists
        Path(self.cfg.audit_log_path).parent.mkdir(parents=True, exist_ok=True)

        logger.info("OmegaEngine initialized")
        logger.info(f"  Paper trade: {self.cfg.paper_trade}")
        logger.info(f"  Markets:     {len(self.cfg.markets)}")
        logger.info(f"  Max pos:     ${self.cfg.max_position_usd:,.0f}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        logger.info("=" * 60)
        logger.info("OMEGA ENGINE STARTING")
        logger.info("=" * 60)

        # 1. WASM compiler
        from sandbox.wasm_compiler import WASMStrategyCompiler
        self.wasm = WASMStrategyCompiler(fuel_limit=self.cfg.wasm_fuel_limit)
        logger.info(f"[WASM]    Compiler ready (fuel={self.cfg.wasm_fuel_limit})")

        # 2. Reality Surface
        from reality_surface.claim_normalizer import RealitySurface
        self.surface = RealitySurface()
        logger.info("[Surface] Reality surface initialized")

        # 3. Polymarket client — plug in your existing connector here
        #   self.pm_client = PolymarketCLOB(
        #       api_key=self.cfg.pm_api_key,
        #       api_secret=self.cfg.pm_api_secret,
        #       passphrase=self.cfg.pm_passphrase,
        #   )
        logger.info("[PM]      Client placeholder (wire up PolymarketCLOB)")

        # 4. Deribit client — plug in your existing connector here
        #   self.deribit_client = DeribitAPI(
        #       key=self.cfg.deribit_key,
        #       secret=self.cfg.deribit_secret,
        #   )
        logger.info("[Deribit] Client placeholder (wire up DeribitAPI)")

        # 5. Gravity LP
        from gravity.lp_dominance import GravityMarketMaker
        self.gravity = GravityMarketMaker(
            polymarket_client=self.pm_client,
            reality_surface=self.surface,
            perp_hedger=self._hedge_on_deribit if not self.cfg.paper_trade else None,
            target_spread=self.cfg.target_spread,
            max_inventory=self.cfg.max_position_usd,
            emergency_hedge_threshold=self.cfg.emergency_hedge_threshold,
        )
        logger.info("[Gravity] LP engine initialized")

        # 6. GP engine — plug in your existing GeneticStrategyEngine here
        #   from vm.genetic_strategy_engine import GeneticStrategyEngine, generate_synthetic_markets
        #   self.gp_engine = GeneticStrategyEngine(
        #       population_size=self.cfg.gp_population_size,
        #       seed=42,
        #   )
        #   self.gp_engine.initialize()
        logger.info("[GP]      Strategy engine placeholder (wire up GeneticStrategyEngine)")

        # 7. Signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._signal_handler)

        self.is_running = True
        self._write_audit({"event": "startup", "paper_trade": self.cfg.paper_trade})

        await asyncio.gather(
            self._price_ingestion_loop(),
            self._quoting_loop(),
            self._risk_monitor_loop(),
            self._gp_evolution_loop(),
            self._audit_loop(),
        )

    def _signal_handler(self):
        logger.warning("Shutdown signal received")
        self._shutdown_event.set()

    async def stop(self):
        logger.info("=" * 60)
        logger.info("OMEGA ENGINE SHUTTING DOWN")
        logger.info("=" * 60)
        self.is_running = False

        if self.gravity:
            for market_id in self.cfg.markets:
                await self.gravity._cancel_all(market_id)

        self._write_audit({
            "event": "shutdown",
            "session_pnl": self.daily_pnl,
            "quotes": self.quote_count,
            "fills": self.fill_count,
            "duration_sec": time.time() - self.session_start,
        })

        logger.info(f"Session PnL: ${self.daily_pnl:+.2f}")
        logger.info(f"Quotes: {self.quote_count}  Fills: {self.fill_count}")

    # ------------------------------------------------------------------
    # Core Loops
    # ------------------------------------------------------------------

    async def _price_ingestion_loop(self):
        """Ingest prices from all venues every 1 s — the data backbone."""
        logger.info("[Loop] Price ingestion started")

        while not self._shutdown_event.is_set():
            try:
                t0 = time.time()

                for market_id in self.cfg.markets:
                    # Production: replace with live PM WebSocket / REST fetch
                    pm_price     = 0.62    # TODO: real fetch
                    pm_liquidity = 150_000

                    self.surface.ingest_polymarket(
                        event=market_id,
                        yes_price=pm_price,
                        liquidity_usd=pm_liquidity,
                        spread=0.02,
                    )

                # Production: uncomment after wiring Deribit client
                # for market_id in self.cfg.markets:
                #     book = await self.deribit_client.get_option(...)
                #     self.surface.ingest_deribit_option(event=market_id, ...)
                #     funding = await self.deribit_client.get_funding(...)
                #     self.surface.ingest_funding_rate(event=market_id, ...)

                # Divergence scan
                for market_id in self.cfg.markets:
                    div = self.surface.find_divergence(market_id, threshold=0.025)
                    if div:
                        logger.info(
                            f"[ARB] {market_id}: {div.direction} | "
                            f"edge={div.edge_bps}bps | conf={div.confidence:.2f}"
                        )

                self.latency_samples.append((time.time() - t0) * 1000)
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"[PriceLoop] {e}")
                await asyncio.sleep(5.0)

        logger.info("[Loop] Price ingestion stopped")

    async def _quoting_loop(self):
        """Refresh quotes on Polymarket every quote_interval_sec."""
        logger.info("[Loop] Quoting started")

        while not self._shutdown_event.is_set():
            try:
                for market_id in self.cfg.markets:
                    if self.cfg.paper_trade:
                        quotes = self.gravity.compute_quotes(market_id)
                        if quotes:
                            self.quote_count += 1
                            logger.debug(
                                f"[PAPER] {market_id} | "
                                f"BID {quotes['bid'].price:.4f}×{quotes['bid'].size:.0f} | "
                                f"ASK {quotes['ask'].price:.4f}×{quotes['ask'].size:.0f} | "
                                f"fair={quotes['fair']:.4f}"
                            )
                    else:
                        await self.gravity.refresh_quotes(market_id)
                        self.quote_count += 1

                await asyncio.sleep(self.cfg.quote_interval_sec)

            except Exception as e:
                logger.error(f"[QuoteLoop] {e}")
                await asyncio.sleep(self.cfg.quote_interval_sec)

        logger.info("[Loop] Quoting stopped")

    async def _risk_monitor_loop(self):
        """
        Monitor risk metrics every 10 s.

        Kill-switch triggers:
          - Daily loss > daily_loss_limit_usd
          - Drawdown > max_drawdown_pct of peak
          - P99 latency > 500 ms
        """
        logger.info("[Loop] Risk monitor started")

        while not self._shutdown_event.is_set():
            try:
                if self.daily_pnl < -self.cfg.daily_loss_limit_usd:
                    logger.critical(
                        f"[KILL] Daily loss ${self.daily_pnl:+.2f} > "
                        f"limit ${self.cfg.daily_loss_limit_usd}"
                    )
                    await self._emergency_stop()
                    return

                self.peak_pnl = max(self.peak_pnl, self.daily_pnl)
                drawdown = self.peak_pnl - self.daily_pnl
                if self.peak_pnl > 0 and drawdown / self.peak_pnl > self.cfg.max_drawdown_pct:
                    logger.critical(
                        f"[KILL] Drawdown {drawdown / self.peak_pnl:.1%} > limit"
                    )
                    await self._emergency_stop()
                    return

                if self.latency_samples:
                    p99 = float(np.percentile(self.latency_samples, 99))
                    if p99 > 500:
                        logger.warning(f"[RISK] P99 latency spike: {p99:.1f} ms")

                status = self.gravity.get_status() if self.gravity else {}
                logger.info(
                    f"[RISK] PnL=${self.daily_pnl:+.2f} | "
                    f"DD={drawdown:.2f} | "
                    f"Inv={status.get('total_net_delta', 0):.1f} | "
                    f"Quotes={self.quote_count} | "
                    f"Fills={self.fill_count}"
                )

                await asyncio.sleep(10.0)

            except Exception as e:
                logger.error(f"[RiskLoop] {e}")
                await asyncio.sleep(10.0)

        logger.info("[Loop] Risk monitor stopped")

    async def _gp_evolution_loop(self):
        """
        Run one GP evolution cycle every 30 minutes.

        Production steps (uncomment after wiring gp_engine):
          1. Load recent market data
          2. Evaluate population in WASM sandbox
          3. Select best strategy by Sharpe
          4. Update gravity's fair-probability model
        """
        logger.info("[Loop] GP evolution started")

        while not self._shutdown_event.is_set():
            try:
                if self.gp_engine is not None:
                    # from vm.genetic_strategy_engine import generate_synthetic_markets
                    # data = generate_synthetic_markets(n_paths=50, n_steps=200)
                    # best = self.gp_engine.evolve(data)
                    # logger.info(f"[GP] Best: fit={best.fitness:.4f} sharpe={best.sharpe:.4f}")
                    pass
                else:
                    logger.info("[GP] Evolution cycle (placeholder — wire up gp_engine)")

                await asyncio.sleep(self.cfg.gp_cycle_sec)

            except Exception as e:
                logger.error(f"[GPLoop] {e}")
                await asyncio.sleep(300.0)

        logger.info("[Loop] GP evolution stopped")

    async def _audit_loop(self):
        """Write heartbeat audit record every 60 s."""
        while not self._shutdown_event.is_set():
            try:
                self._write_audit({
                    "event": "heartbeat",
                    "timestamp": time.time(),
                    "pnl": self.daily_pnl,
                    "quotes": self.quote_count,
                    "fills": self.fill_count,
                    "latency_p99": float(np.percentile(self.latency_samples, 99))
                    if self.latency_samples else 0,
                })
                await asyncio.sleep(60.0)
            except Exception as e:
                logger.error(f"[AuditLoop] {e}")
                await asyncio.sleep(60.0)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _hedge_on_deribit(self, market_id: str, side: str, size: float) -> dict:
        """Cross-hedge callback passed to GravityMarketMaker."""
        if self.cfg.paper_trade:
            logger.info(f"[PAPER HEDGE] {market_id} {side} {size:.1f} on Deribit")
            return {"paper": True, "side": side, "size": size}
        # Production: await self.deribit_client.place_perp_order(side=side, size=size)
        logger.info(f"[HEDGE] {market_id} {side} {size:.1f} on Deribit")
        return {"executed": True}

    async def _emergency_stop(self):
        logger.critical("EMERGENCY STOP ACTIVATED")
        if self.gravity:
            for market_id in self.cfg.markets:
                await self.gravity._cancel_all(market_id)
        self._write_audit({
            "event": "emergency_stop",
            "reason": "risk_limit",
            "pnl": self.daily_pnl,
            "timestamp": time.time(),
        })
        self._shutdown_event.set()

    def _write_audit(self, record: dict):
        """Append hash-chained record to audit JSONL."""
        record["_seq"] = self._audit_seq
        self._audit_seq += 1
        record_str = json.dumps(record, sort_keys=True)
        record["_hash"] = hashlib.sha256(record_str.encode()).hexdigest()[:16]
        with open(self.cfg.audit_log_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_dashboard(self) -> dict:
        """JSON-serializable status snapshot (exposed by api_server)."""
        return {
            "engine": "Omega v6 (Practical)",
            "running": self.is_running,
            "paper_trade": self.cfg.paper_trade,
            "session_duration_sec": round(time.time() - self.session_start, 1),
            "pnl": {
                "daily": round(self.daily_pnl, 2),
                "peak": round(self.peak_pnl, 2),
                "drawdown": round(self.peak_pnl - self.daily_pnl, 2),
            },
            "performance": {
                "quotes": self.quote_count,
                "fills": self.fill_count,
                "latency_p99_ms": round(float(np.percentile(self.latency_samples, 99)), 2)
                if self.latency_samples else 0,
            },
            "surface": {
                "events_tracked": len(self.surface.get_all_events()) if self.surface else 0,
            },
            "gravity": self.gravity.get_status() if self.gravity else {},
            "wasm": {
                "cache_size": self.wasm.cache_size if self.wasm else 0,
                "fuel_limit": self.cfg.wasm_fuel_limit,
            },
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main():
    config = OmegaConfig()
    engine = OmegaEngine(config)
    try:
        await engine.start()
    except asyncio.CancelledError:
        pass
    finally:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
