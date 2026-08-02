# Genesis Engine v6 — Omega Stack

> **Axiom:** *"The final form of alpha is not extraction. It is creation."*

The Genesis Engine is a Python aiohttp service that evolves trading strategies via genetic programming in a fuel-metered bytecode VM, and quotes prediction markets through an inventory-aware market-making layer.

---

## File tree

```
artifacts/genesis-engine/
├── run.py                          # aiohttp entry point — sets sys.path, starts api_server.py
├── omega_engine.py                 # v6 standalone orchestrator (5 async loops)
├── requirements.txt
├── ARCHITECTURE_v5.0.md            # Original v5 design vision document
└── src/
    ├── api_server.py               # aiohttp REST API (health, status, evolve, etc.)
    │
    ├── api/                        # Market connectors (present; not started by default)
    │   ├── polymarket_client.py    # Polymarket CLOB — REST + WS, HMAC auth, order mgmt
    │   ├── binance_client.py       # Binance USD-M perps — funding, klines, orders
    │   ├── bybit_client.py         # Bybit V5 linear perps — funding, order book streaming
    │   └── deribit_client.py       # Deribit options + futures — sig auth, options chain
    │
    ├── microstructure/
    │   ├── orderbook.py            # Unified L2 aggregation, VPIN, OFI, trade intensity
    │   ├── slippage_model.py       # Book-walk + power-law depth extrapolation
    │   └── toxic_flow.py           # VPIN, Kyle lambda, OFI, adverse selection score
    │
    ├── strategies/
    │   ├── base.py                 # Abstract strategy — risk/slippage hooks, enable/disable
    │   ├── funding_arb.py          # Cross-venue funding rate arbitrage (Binance/Bybit/Deribit)
    │   ├── perp_hedge.py           # Delta-neutral Polymarket → CEX perp hedge
    │   └── llm_invention.py        # GPT-4o strategy invention + VM backtest + auto-deploy
    │
    ├── risk/
    │   ├── position_manager.py     # Multi-venue position book, exposure limits, leverage caps
    │   └── portfolio_risk.py       # CVaR(95%), correlation monitoring, drawdown circuit breakers
    │
    ├── swarm/
    │   ├── redis_cache.py          # Pub/sub alpha signals, funding cache, agent heartbeat
    │   └── neo4j_graph.py          # Knowledge graph: (Agent)-[:REPORTS]->(Alpha)-[:TARGETS]->(Market)
    │
    ├── vm/                         # Core containment substrate (v5, patched to v6)
    │   ├── bytecode_vm.py          # Fuel-metered stack VM — 16 opcodes, depth/stack guards
    │   ├── genetic_strategy_engine.py  # GP engine — evolve, crossover, mutate, Sharpe-first selection
    │   ├── portfolio.py            # Ensemble: Sharpe, Calmar, max drawdown, pairwise correlation
    │   ├── audit_trail.py          # Append-only hash-chained JSONL audit log
    │   └── measure_boundary.py     # 7-test containment stress suite
    │
    ├── patches/                    # ── NEW v6 ──
    │   ├── vm_hardening_patch.py   # SafeMath (NaN-propagating), FitnessGate (±1000 cap), AuditSanitizer
    │   └── gp_selection_fixes.py   # LexicographicSelector, DiversityPreserver, SharpeFirstElitism
    │
    ├── reality_surface/            # ── NEW v6 ──
    │   └── claim_normalizer.py     # RealitySurface — cross-venue probability consensus + divergence
    │
    ├── gravity/                    # ── NEW v6 ──
    │   └── lp_dominance.py         # GravityMarketMaker — inventory-skewed CLOB quoting
    │
    └── sandbox/                    # ── NEW v6 ──
        └── wasm_compiler.py        # WASMStrategyCompiler — wasmtime backend + SafePythonVM fallback
```

---

## What is implemented

### VM + GP core (v5, patched to v6)

| Component | File | Status |
|-----------|------|--------|
| Fuel-metered bytecode VM | `vm/bytecode_vm.py` | **Live** — 16 opcodes, stack limits, compile-depth guards. v6: NaN-propagating SafeMath (div/log/exp) |
| Genetic strategy evolution | `vm/genetic_strategy_engine.py` | **Live** — subtree crossover, point mutation, causal DAG terminals, regime-shift world model. v6: `sharpe` field, FitnessGate, Sharpe-first selection, diversity re-seeding |
| Ensemble evaluation | `vm/portfolio.py` | **Live** — Sharpe, Calmar, max drawdown, pairwise correlation |
| Immutable audit trail | `vm/audit_trail.py` | **Live** — append-only JSONL with SHA-256 hash chain |
| Containment stress suite | `vm/measure_boundary.py` | **Live** — 7 tests: fuel exhaustion, stack overflow, compiler rejection, determinism, throughput, adversarial failure |

### v6 Omega modules

| Module | File | What it does |
|--------|------|-------------|
| VM Hardening | `patches/vm_hardening_patch.py` | `SafeMath`: div/log/exp return NaN on invalid input (prevents fitness inflation). `FitnessGate`: 6-layer sanitizer — NaN kill, Inf kill, sign consistency (positive fitness + negative Sharpe → reject), hard cap ±1000. `AuditSanitizer`: strips NaN/Inf before writing to audit chain. |
| GP Selection Fixes | `patches/gp_selection_fixes.py` | `LexicographicSelector`: Sharpe-first tournament (a Sharpe=1.2, fitness=0.8 genome beats Sharpe=-5.88, fitness=11M). `DiversityPreserver`: niche penalty + re-seeding when diversity < 85%. `SharpeFirstElitism`: Hall of Fame sorted by (Sharpe, fitness). |
| Reality Surface | `reality_surface/claim_normalizer.py` | `RealitySurface`: ingests PM prices, Deribit IV, funding rates, insurance premiums → confidence-weighted consensus probability. `find_divergence()` returns cross-venue edge signals with bps magnitude. |
| Gravity LP | `gravity/lp_dominance.py` | `GravityMarketMaker`: inventory-skewed Polymarket CLOB quoting. Dynamic spread = base × (1 + γ·|inventory|). Phase-shifted bid/ask curves driven by net inventory. Auto-hedge callback when `|inventory| > max_pos`. |
| WASM Sandbox | `sandbox/wasm_compiler.py` | `WASMStrategyCompiler`: compiles GP expression AST → WAT → WASM binary via wasmtime. Fuel-metered and deterministic. `SafePythonVM`: fallback when wasmtime absent — same interface, Python execution. |
| Omega Orchestrator | `omega_engine.py` | `OmegaEngine`: 5 async loops — price ingestion (1 s), quoting (3 s), risk monitor (10 s), GP evolution (30 min), audit heartbeat (60 s). `paper_trade=True` by default. Dashboard via `get_dashboard()`. |

### Market infrastructure (present, not started by default)

| Layer | File | Status |
|-------|------|--------|
| Polymarket CLOB | `api/polymarket_client.py` | **Present** — REST + WS, HMAC auth, order book, positions |
| Binance USD-M | `api/binance_client.py` | **Present** — perps, funding, klines, order management |
| Bybit V5 | `api/bybit_client.py` | **Present** — linear perps, funding, order book streaming |
| Deribit Options | `api/deribit_client.py` | **Present** — signature auth, options chain, perp hedging |
| Unified order book | `microstructure/orderbook.py` | **Present** — multi-venue L2 aggregation, weighted mid, depth, imbalance |
| Slippage model | `microstructure/slippage_model.py` | **Present** — book-walk + power-law depth extrapolation |
| Toxic flow detector | `microstructure/toxic_flow.py` | **Present** — VPIN, Kyle lambda, OFI, adverse selection |

### Strategy suite (not activated by default)

| Strategy | File | Logic |
|----------|------|-------|
| Funding Arb | `strategies/funding_arb.py` | Scans Binance/Bybit/Deribit. Shorts high, longs low when divergence > threshold and carry > costs. |
| Perp Hedge | `strategies/perp_hedge.py` | Maintains delta-neutral book. Polymarket position → auto-hedge via cheapest-cost CEX perp. |
| LLM Invention | `strategies/llm_invention.py` | Prompts GPT-4o with regime + DSL. Compiles → AST → VM backtest. Auto-deploys if Sharpe improvement > 20%. |

---

## Feature vector (16 terminals)

```
0–9   mid, spread, imbalance, volume, rsi, zscore, momentum, volatility, time_frac, prev_signal
10–13 do_imbalance, causal_mid, shock, confounder    ← causal / intervention
14–15 regime, regime_age                             ← regime indicators
```

---

## Quick start (Replit)

```bash
# From workspace root
pip install -r artifacts/genesis-engine/requirements.txt

# Start the engine (via the Replit workflow panel, or directly):
cd artifacts/genesis-engine && python run.py

# Start the standalone Omega orchestrator:
cd artifacts/genesis-engine && python omega_engine.py

# Run the boundary stress suite:
cd artifacts/genesis-engine && python -m src.vm.measure_boundary

# Run a quick evolution smoke test:
cd artifacts/genesis-engine && python -c "
from src.vm.genetic_strategy_engine import GeneticStrategyEngine, generate_synthetic_markets
e = GeneticStrategyEngine(population_size=20, seed=42)
e.initialize()
best = e.evolve(generate_synthetic_markets(n_paths=10, n_steps=50))
print(f'best sharpe={best.sharpe:.3f} fitness={best.fitness:.4f}')
"
```

---

## v6 key invariants

1. **NaN propagation** — any invalid arithmetic in the VM stack propagates NaN upward; FitnessGate kills the genome cleanly before it can corrupt the population.
2. **Sharpe-first selection** — no genome with negative Sharpe can beat a positive-Sharpe genome regardless of raw fitness magnitude.
3. **Fitness cap** — fitness is hard-capped at ±1000 after the v6 audit found 11.6M outliers (14% of population) with root cause `div(..., imbalance)` hitting near-zero + `log(negative)`.
4. **Diversity preservation** — population re-seeded (15% fresh random genomes) every 5 generations or when unique-source fraction drops below 85%.
5. **Paper mode default** — `omega_engine.py` starts with `paper_trade=True`. Set `PAPER_TRADE=false` only after extended paper validation.

---

## Design rule

**Ship enforceable features.** Everything in `src/` compiles and runs. The architecture document (`ARCHITECTURE_v5.0.md`) describes the full vision; the codebase delivers the measured, enforceable substrate that makes everything else possible.
