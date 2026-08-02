#!/usr/bin/env python3
"""
Genesis Engine v5.0 — Production Orchestrator
==============================================
Wires together:
  - Polymarket CLOB + CEX venues (Binance, Bybit, Deribit)
  - Redis cache + Neo4j knowledge graph
  - Microstructure engine (slippage, toxic flow)
  - Strategy suite (funding arb, perp hedge, LLM invention)
  - Risk engine (position manager, portfolio risk, circuit breakers)
  - VM-contained genetic strategies (from v5-alpha substrate)

Run:
    docker-compose up -d   # Start Redis + Neo4j
    export POLYMARKET_API_KEY=...
    export BINANCE_API_KEY=...
    export OPENAI_API_KEY=...
    python -m src.main
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from decimal import Decimal
from typing import Any, Dict, List

from src.config_loader import load_config
from src.api.polymarket_client import PolymarketClient
from src.api.binance_client import BinanceClient
from src.api.bybit_client import BybitClient
from src.api.deribit_client import DeribitClient
from src.swarm.redis_cache import RedisSwarmCache
from src.swarm.neo4j_graph import Neo4jKnowledgeGraph
from src.microstructure.orderbook import UnifiedOrderBook, UnifiedBookLevel, MicrostructureEngine
from src.microstructure.slippage_model import SlippageModel
from src.microstructure.toxic_flow import ToxicFlowDetector
from src.strategies.funding_arb import FundingArbitrage
from src.strategies.perp_hedge import PerpHedgeStrategy
from src.strategies.llm_invention import LLMStrategyInvention
from src.risk.position_manager import PositionManager
from src.risk.portfolio_risk import PortfolioRiskEngine
from src.vm.genetic_strategy_engine import GeneticStrategyEngine, generate_synthetic_markets
from src.vm.audit_trail import AuditTrail


class GenesisEngine:
    def __init__(self):
        self.cfg = load_config("config/config.yaml")
        self.running = False

        # API clients
        self.poly: PolymarketClient | None = None
        self.binance: BinanceClient | None = None
        self.bybit: BybitClient | None = None
        self.deribit: DeribitClient | None = None

        # Swarm infra
        self.redis: RedisSwarmCache | None = None
        self.neo4j: Neo4jKnowledgeGraph | None = None

        # Risk & execution
        self.pm = PositionManager(
            max_portfolio_exposure=self.cfg.risk.max_portfolio_exposure_usd,
            max_position_size=self.cfg.risk.max_single_market_exposure_usd,
        )
        self.risk = PortfolioRiskEngine(
            max_drawdown_pct=self.cfg.risk.max_drawdown_pct,
            daily_loss_limit_usd=self.cfg.risk.daily_loss_limit_usd,
        )
        self.slippage = SlippageModel(model_type="naive")

        # Strategies
        self.strategies: List[Any] = []
        self.funding_arb: FundingArbitrage | None = None
        self.perp_hedge: PerpHedgeStrategy | None = None
        self.llm_invention: LLMStrategyInvention | None = None

        # Microstructure
        self.micro_engines: Dict[str, MicrostructureEngine] = {}
        self.toxic_detectors: Dict[str, ToxicFlowDetector] = {}

        # Audit
        os.makedirs("logs", exist_ok=True)
        self.audit = AuditTrail("logs/audit_live.jsonl")

        # Genetic substrate (offline evolution thread)
        self.gp_engine: GeneticStrategyEngine | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        print("=" * 72)
        print("Genesis Engine v5.0 — Production Orchestrator")
        print("=" * 72)

        # Swarm infrastructure
        self.redis = RedisSwarmCache(
            host=self.cfg.redis.host,
            port=self.cfg.redis.port,
        )
        await self.redis.connect()
        print("[OK] Redis connected")

        self.neo4j = Neo4jKnowledgeGraph(
            uri=self.cfg.neo4j.uri,
            user=self.cfg.neo4j.user,
            password=self.cfg.neo4j.password,
        )
        await self.neo4j.connect()
        await self.neo4j.init_schema()
        print("[OK] Neo4j connected")

        # Exchange clients
        if self.cfg.polymarket.api_key:
            self.poly = PolymarketClient(
                api_key=self.cfg.polymarket.api_key,
                api_secret=self.cfg.polymarket.api_secret,
                passphrase=self.cfg.polymarket.passphrase,
            )
            await self.poly.start()
            print("[OK] Polymarket client ready")

        if self.cfg.binance.api_key:
            self.binance = BinanceClient(
                api_key=self.cfg.binance.api_key,
                api_secret=self.cfg.binance.api_secret,
                testnet=self.cfg.binance.testnet,
            )
            await self.binance.start()
            print("[OK] Binance client ready")

        if self.cfg.bybit.api_key:
            self.bybit = BybitClient(
                api_key=self.cfg.bybit.api_key,
                api_secret=self.cfg.bybit.api_secret,
                testnet=self.cfg.bybit.testnet,
            )
            await self.bybit.start()
            print("[OK] Bybit client ready")

        if self.cfg.deribit.client_id:
            self.deribit = DeribitClient(
                client_id=self.cfg.deribit.client_id,
                client_secret=self.cfg.deribit.client_secret,
                testnet=self.cfg.deribit.testnet,
            )
            await self.deribit.start()
            print("[OK] Deribit client ready")

        # Strategies
        self.funding_arb = FundingArbitrage(
            strategy_id="funding_arb_v1",
            position_manager=self.pm,
            slippage_model=self.slippage,
        )
        self.strategies.append(self.funding_arb)

        self.perp_hedge = PerpHedgeStrategy(
            strategy_id="perp_hedge_v1",
            position_manager=self.pm,
            slippage_model=self.slippage,
        )
        self.strategies.append(self.perp_hedge)

        if self.cfg.llm.api_key:
            self.llm_invention = LLMStrategyInvention(
                api_key=self.cfg.llm.api_key,
                model=self.cfg.llm.model,
                deployment_threshold=0.20,
                audit=self.audit,
            )
            print("[OK] LLM invention engine ready")

        # Genetic engine (background evolution)
        self.gp_engine = GeneticStrategyEngine(
            population_size=40,
            max_depth=5,
            seed=42,
            audit=self.audit,
        )
        self.gp_engine.initialize()
        print("[OK] Genetic engine initialized")

        # Register agents in knowledge graph
        await self.neo4j.add_agent("orchestrator", "treasury_guardian")
        await self.neo4j.add_agent("funding_arb_v1", "arbitrageur")
        await self.neo4j.add_agent("perp_hedge_v1", "hedger")
        print("[OK] Agents registered in knowledge graph")

        self.running = True
        print("\n[READY] All systems operational. Entering event loop...")

    async def stop(self):
        self.running = False
        if self.poly:
            await self.poly.stop()
        if self.binance:
            await self.binance.stop()
        if self.bybit:
            await self.bybit.stop()
        if self.deribit:
            await self.deribit.stop()
        if self.redis:
            await self.redis.disconnect()
        if self.neo4j:
            await self.neo4j.disconnect()
        print("[STOP] All clients disconnected.")

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    async def run(self):
        await self.start()

        # Schedule background tasks
        tasks = [
            asyncio.create_task(self._market_data_loop()),
            asyncio.create_task(self._strategy_loop()),
            asyncio.create_task(self._risk_loop()),
            asyncio.create_task(self._gp_loop()),
        ]

        # Graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _market_data_loop(self):
        """Poll funding rates, order books, and cache to Redis."""
        while self.running:
            try:
                # Funding rates
                if self.binance:
                    rates = await self.binance.get_all_funding_rates()
                    for r in rates:
                        sym = r.get("symbol", "")
                        rate = float(r.get("lastFundingRate", 0))
                        await self.redis.set_funding("binance", sym, rate)

                if self.bybit:
                    rates = await self.bybit.get_all_funding_rates()
                    for r in rates:
                        sym = r.get("symbol", "")
                        rate = float(r.get("fundingRate", 0))
                        await self.redis.set_funding("bybit", sym, rate)

                # Polymarket positions
                if self.poly:
                    positions = await self.poly.get_positions()
                    for pos in positions:
                        tid = pos.get("asset_id") or pos.get("token_id")
                        size = float(pos.get("size", 0))
                        await self.redis.set_position("polymarket", tid, size)

                # Cache portfolio value
                total = self.pm.total_exposure_usd()
                await self.redis.set_portfolio_value(total)

            except Exception as e:
                print(f"[MARKET_DATA] Error: {e}")

            await asyncio.sleep(30)

    async def _strategy_loop(self):
        """Run strategy evaluation and signal generation."""
        while self.running:
            try:
                # Funding arb signal
                if self.funding_arb:
                    symbols = ["BTCUSDT", "ETHUSDT"]
                    for sym in symbols:
                        venues = {}
                        for v in ["binance", "bybit"]:
                            rate = await self.redis.get_funding(v, sym)
                            if rate is not None:
                                venues[v] = {"rate": rate, "next": 0}
                        if len(venues) >= 2:
                            sig = await self.funding_arb.on_market_data({
                                "type": "funding_snapshot",
                                "symbol": sym,
                                "venues": venues,
                            })
                            if sig and self.funding_arb.check_risk(sig):
                                await self.redis.publish_signal("genesis:signals", {
                                    "strategy": sig.strategy_id,
                                    "venue": sig.venue,
                                    "symbol": sig.symbol,
                                    "side": sig.side,
                                    "size": float(sig.size),
                                    "confidence": sig.confidence,
                                    "metadata": sig.metadata,
                                })

                # LLM invention (run every hour)
                if self.llm_invention and int(asyncio.get_event_loop().time()) % 3600 < 60:
                    ctx = {
                        "regime": "stress" if self.risk.check_circuit_breaker() else "normal",
                        "best_fitness": 0.0,
                        "avg_fitness": 0.0,
                        "stagnation_generations": 0,
                        "top_strategy_source": "N/A",
                    }
                    invention = await self.llm_invention.invent(ctx)
                    if invention and invention.get("deployed"):
                        print(f"[LLM] Deployed new strategy: {invention['source'][:60]}")

            except Exception as e:
                print(f"[STRATEGY] Error: {e}")

            await asyncio.sleep(10)

    async def _risk_loop(self):
        """Continuous risk monitoring."""
        while self.running:
            try:
                value = await self.redis.get_portfolio_value()
                self.risk.on_portfolio_update(value, {})
                state = self.risk.get_state()

                if state.circuit_breaker:
                    print(f"[RISK] CIRCUIT BREAKER TRIGGERED! DD={state.max_drawdown:.2%}")
                    for s in self.strategies:
                        s.disable()
                    await self.redis.publish_signal("genesis:alerts", {
                        "type": "circuit_breaker",
                        "max_drawdown": state.max_drawdown,
                        "portfolio_value": state.portfolio_value,
                    })

                self.audit.log(
                    event="RISK_SNAPSHOT",
                    genome_id="portfolio",
                    source="risk_engine",
                    bytecode_hash="",
                    n_ops=0,
                    fitness=state.portfolio_value,
                    fuel_limit=0,
                    extra=state.__dict__,
                )

            except Exception as e:
                print(f"[RISK] Error: {e}")

            await asyncio.sleep(5)

    async def _gp_loop(self):
        """Background genetic programming evolution."""
        while self.running:
            try:
                data = generate_synthetic_markets(n_paths=10, n_steps=50, seed=None)
                best = self.gp_engine.evolve(data)
                print(f"[GP] Gen {self.gp_engine.generation} best={best.fitness:.4f}")
            except Exception as e:
                print(f"[GP] Error: {e}")
            await asyncio.sleep(300)


def main():
    engine = GenesisEngine()
    asyncio.run(engine.run())


if __name__ == "__main__":
    main()
