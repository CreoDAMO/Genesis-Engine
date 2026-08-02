# Genesis Engine v5.0 — Production Stack
## Recursive Autopoietic Alpha Organism

> **Axiom:** *"The final form of alpha is not extraction. It is creation."*

---

## File Tree

```
genesis_engine_v5/
├── ARCHITECTURE_v5.0.md          # Full v5 design document (vision)
├── README.md                      # This file
├── config/
│   └── config.yaml                # API keys, risk limits, infra endpoints
├── docker-compose.yml             # Redis + Neo4j services
├── requirements.txt               # Python dependencies
├── src/
│   ├── __init__.py
│   ├── main.py                    # Production orchestrator (event loop)
│   ├── config_loader.py           # YAML config with env var substitution
│   ├── api/
│   │   ├── __init__.py
│   │   ├── polymarket_client.py   # CLOB REST + WS, auth, order mgmt
│   │   ├── binance_client.py      # USD-M perps, funding, order book
│   │   ├── bybit_client.py        # V5 unified trading, perps
│   │   └── deribit_client.py      # Options + futures, signature auth
│   ├── microstructure/
│   │   ├── __init__.py
│   │   ├── orderbook.py           # Unified L2, VPIN, OFI, trade intensity
│   │   ├── slippage_model.py      # Book-walk + power-law extrapolation
│   │   └── toxic_flow.py          # VPIN + Kyle lambda + adverse selection
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py                # Abstract strategy with risk/slippage hooks
│   │   ├── funding_arb.py         # Cross-venue funding rate arbitrage
│   │   ├── perp_hedge.py          # Delta-neutral Polymarket -> CEX hedge
│   │   └── llm_invention.py       # GPT-4o strategy invention + auto-deploy
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── position_manager.py    # Multi-venue position book + exposure limits
│   │   └── portfolio_risk.py      # CVaR, correlation, drawdown circuit breakers
│   ├── swarm/
│   │   ├── __init__.py
│   │   ├── redis_cache.py         # Pub/sub signals, agent registry, state cache
│   │   └── neo4j_graph.py         # Knowledge graph: strategies, alphas, agents
│   └── vm/
│       ├── __init__.py
│       ├── bytecode_vm.py         # Fuel-metered stack VM (containment boundary)
│       ├── genetic_strategy_engine.py  # GP evolution, causal DAG, regime shifts
│       ├── portfolio.py           # Ensemble evaluation (Sharpe, Calmar, DD)
│       ├── audit_trail.py         # Immutable hash-chained JSONL
│       └── measure_boundary.py    # 7-test containment stress suite
└── tests/
    ├── __init__.py
    └── test_microstructure.py     # Unit tests for book, slippage, toxic flow
```

---

## What is implemented

### Tier 1: Containment Substrate (from v5.0-alpha)

| Layer | File | Status |
|-------|------|--------|
| Fuel-metered bytecode VM | `vm/bytecode_vm.py` | Live — 16 opcodes, stack limits, compile-depth guards |
| Genetic expression-tree evolution | `vm/genetic_strategy_engine.py` | Live — tournament selection, subtree crossover, point mutation |
| Causal / intervention terminals | `vm/genetic_strategy_engine.py` | Live — confounder → imbalance → mid DAG, do(imbalance) |
| Regime-shift world model | `vm/genetic_strategy_engine.py` | Live — calm ↔ stress switching mid-path |
| Strategy ensemble / portfolio | `vm/portfolio.py` | Live — Sharpe, Calmar, max drawdown, pairwise correlation |
| Immutable audit trail | `vm/audit_trail.py` | Live — append-only JSONL with hash chain |
| Boundary stress suite | `vm/measure_boundary.py` | Live — fuel exhaustion, stack overflow, compiler rejection, determinism, throughput, adversarial failure |

### Tier 2: Live Market Infrastructure

| Layer | File | Status |
|-------|------|--------|
| Polymarket CLOB client | `api/polymarket_client.py` | Live — REST + WS, HMAC auth, order book reconstruction, position tracking |
| Binance USD-M Futures | `api/binance_client.py` | Live — perps, funding rates, klines, order mgmt |
| Bybit V5 Unified | `api/bybit_client.py` | Live — linear perps, funding, order book streaming |
| Deribit Options + Futures | `api/deribit_client.py` | Live — signature auth, options chain, perp hedging |
| Unified order book | `microstructure/orderbook.py` | Live — multi-venue L2 aggregation, weighted mid, depth, imbalance |
| Slippage model | `microstructure/slippage_model.py` | Live — book-walk + power-law depth extrapolation |
| Toxic flow detector | `microstructure/toxic_flow.py` | Live — VPIN, Kyle lambda, OFI, adverse selection |

### Tier 3: Strategy Suite

| Strategy | File | Logic |
|----------|------|-------|
| Funding Arbitrage | `strategies/funding_arb.py` | Scans Binance/Bybit/Deribit funding rates. Shorts high, longs low when divergence > threshold + carry > costs. |
| Perp Hedge | `strategies/perp_hedge.py` | Maintains delta-neutral book. Polymarket position → auto-hedge via cheapest CEX perp. |
| LLM Invention | `strategies/llm_invention.py` | Prompts GPT-4o with market regime + DSL. Compiles to AST, backtests in VM, auto-deploys if >20% improvement. |

### Tier 4: Risk & Execution

| Layer | File | Status |
|-------|------|--------|
| Position manager | `risk/position_manager.py` | Live — multi-venue position book, exposure limits, leverage caps |
| Portfolio risk engine | `risk/portfolio_risk.py` | Live — CVaR(95%), correlation monitoring, drawdown + daily loss circuit breakers |
| Strategy base class | `strategies/base.py` | Live — pre-flight risk checks, slippage estimation, enable/disable |

### Tier 5: Swarm Infrastructure

| Layer | File | Status |
|-------|------|--------|
| Redis cache | `swarm/redis_cache.py` | Live — pub/sub alpha signals, funding rate cache, position state, agent heartbeat |
| Neo4j knowledge graph | `swarm/neo4j_graph.py` | Live — semantic triples: (Agent)-[:REPORTS]->(Alpha)-[:TARGETS]->(Market) |
| Orchestrator | `main.py` | Live — async event loop, background tasks, graceful shutdown |

---

## Feature Vector (16 terminals)

```
0-9   mid, spread, imbalance, volume, rsi, zscore, momentum, volatility, time_frac, prev_signal
10-13 do_imbalance, causal_mid, shock, confounder     ← causal / intervention
14-15 regime, regime_age                              ← regime indicators
```

---

## Quick Start

### 1. Start infrastructure

```bash
docker-compose up -d
```

### 2. Configure secrets

```bash
export POLYMARKET_API_KEY="..."
export POLYMARKET_API_SECRET="..."
export POLYMARKET_PASSPHRASE="..."
export BINANCE_API_KEY="..."
export BINANCE_API_SECRET="..."
export BYBIT_API_KEY="..."
export BYBIT_API_SECRET="..."
export DERIBIT_CLIENT_ID="..."
export DERIBIT_CLIENT_SECRET="..."
export OPENAI_API_KEY="..."
```

### 3. Install & run

```bash
pip install -r requirements.txt
python -m src.main
```

### 4. Run tests

```bash
pytest tests/
```

### 5. Run VM boundary suite

```bash
python -m src.vm.measure_boundary
```

### 6. Run genetic evolution demo

```bash
python -m src.vm.genetic_strategy_engine
```

---

## Architecture vs Implementation

| Vision (ARCHITECTURE_v5.0.md) | Status | Notes |
|---|---|---|
| Autopoietic Strategy Genesis (GP + LLM) | **Implemented** | `genetic_strategy_engine.py` + `llm_invention.py` |
| World Simulator (causal DAG) | **Implemented** | Synthetic causal DAG in `generate_synthetic_markets()` |
| Market Genesis Protocol | Architecture | On-chain market creation requires UMA/Kleros oracle integration |
| Multi-Agent Swarm Treasury | **Partial** | Redis + Neo4j swarm layer live; DAO treasury & legal personhood are architecture |
| Biological Immunity | Architecture | Adaptive patch generation requires TEE-ZK mesh + LLM critique loop |
| Recursive Self-Improvement | Architecture | Singularity Loop requires host-code rewriting + sandbox A/B testing |
| Quantum Annealing | Architecture | D-Wave/QAOA integration is future work |

---

## Design Rule

**Ship enforceable features.** Everything in `src/` compiles and runs. The architecture document describes the full vision; the codebase delivers the measured, enforceable substrate that makes everything else possible.
