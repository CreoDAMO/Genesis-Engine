# Genesis Strategy Console

An evolutionary trading-strategy research platform built as a pnpm monorepo on Replit. A Python engine evolves expression-tree strategies using a fuel-metered bytecode VM and genetic programming; an Express proxy bridges it to a React terminal console that visualises fitness, market-making state, and an immutable audit trail in real time.

---

## Monorepo layout

```
/
├── artifacts/
│   ├── genesis-engine/          # Python — aiohttp API + GP engine (port 8000)
│   ├── api-server/              # Express 5 — proxy & REST layer (port 8080)
│   └── genesis-console/         # React + Vite terminal console (artifact-managed port)
├── lib/
│   ├── api-spec/                # OpenAPI spec → typed hooks via Orval codegen
│   └── db/                      # Drizzle ORM schema (PostgreSQL, not yet wired)
├── pnpm-workspace.yaml
└── README.md
```

---

## Services

| Service | Workflow | Technology | Role |
|---------|----------|------------|------|
| Genesis Engine | `Genesis Engine (Python)` | aiohttp + numpy | GP evolution, market data, VM |
| API Server | `artifacts/api-server: API Server` | Express 5 + TypeScript | Proxy `/api/genesis/*` to Python |
| Genesis Console | `artifacts/genesis-console: web` | React + Vite + Tailwind | Terminal UI |

---

## Quick start (Replit)

```bash
pnpm install                       # install all workspace deps
# Restart all three workflows from the workflow panel, then open the preview
```

```bash
# Python deps (genesis engine only)
cd artifacts/genesis-engine
pip install -r requirements.txt
```

---

## Python engine — `artifacts/genesis-engine/`

### Entry points

| File | Purpose |
|------|---------|
| `run.py` | aiohttp server entry point — sets `sys.path`, starts `api_server.py` on port 8000 |
| `omega_engine.py` | Standalone v6 orchestrator — 5 async loops: price ingestion (1 s), quoting (3 s), risk monitor (10 s), GP evolution (30 min), audit heartbeat (60 s). `paper_trade=True` by default. |

### `src/vm/` — Containment substrate (v5 + v6 patches)

| File | What it does |
|------|-------------|
| `bytecode_vm.py` | Fuel-metered stack VM. 16 opcodes, stack/depth guards. **v6:** `safe_div` returns NaN for x/~0; `safe_log` returns NaN for non-positive; `safe_exp` bounds ±709/745. |
| `genetic_strategy_engine.py` | GP engine: tournament selection, subtree crossover, point mutation, causal DAG terminals, regime-shift world model. **v6:** `StrategyGenome.sharpe` field; `FitnessGate` on every eval; Sharpe-first `_pick_parent`; diversity-preserving `evolve` with 15% re-seeding. |
| `portfolio.py` | Ensemble metrics: Sharpe, Calmar, max drawdown, pairwise correlation. |
| `audit_trail.py` | Append-only hash-chained JSONL audit log. |
| `measure_boundary.py` | 7-test containment stress suite (fuel exhaustion, stack overflow, compiler rejection, determinism, throughput, adversarial). |

### `src/patches/` — v6 safety layer

| File | Key classes |
|------|------------|
| `vm_hardening_patch.py` | `SafeMath` (NaN-propagating div/log/exp), `FitnessGate` (6-layer sanitizer, hard cap ±1000, kills positive-fitness/negative-Sharpe genomes), `AuditSanitizer` (poison detection before JSONL write) |
| `gp_selection_fixes.py` | `LexicographicSelector` (Sharpe-first tournament), `DiversityPreserver` (niche penalty + re-seeding), `SharpeFirstElitism` |

### `src/reality_surface/` — v6 probability consensus

| File | What it does |
|------|-------------|
| `claim_normalizer.py` | `RealitySurface` — ingests PM prices, Deribit options IV, funding rates, insurance premiums; emits confidence-weighted consensus probability. `find_divergence()` returns cross-venue edge signals. |

### `src/gravity/` — v6 market making

| File | What it does |
|------|-------------|
| `lp_dominance.py` | `GravityMarketMaker` — inventory-skewed Polymarket CLOB quoting: dynamic spread, phase-shifted bid/ask curves driven by net inventory, auto-hedge callback. |

### `src/sandbox/` — v6 execution sandbox

| File | What it does |
|------|-------------|
| `wasm_compiler.py` | `WASMStrategyCompiler` — compiles GP expression trees to WASM binary via `wasmtime` (fuel-metered, deterministic). Falls back to `SafePythonVM` if wasmtime is not installed (`pip install wasmtime` to enable). |

### `src/api/` — Market connectors (present, not started by default)

`polymarket_client.py`, `binance_client.py`, `bybit_client.py`, `deribit_client.py` — REST + WebSocket clients. Wired as stubs in `omega_engine.py`; active once credentials are in env secrets.

### `src/microstructure/`

`orderbook.py` (unified L2, VPIN, OFI), `slippage_model.py` (book-walk + power-law), `toxic_flow.py` (Kyle lambda, adverse selection).

### `src/strategies/`

`funding_arb.py`, `perp_hedge.py`, `llm_invention.py` (GPT-4o strategy invention + auto-deploy).

### `src/risk/`

`position_manager.py` (multi-venue exposure), `portfolio_risk.py` (CVaR 95%, drawdown circuit breakers).

### Feature vector (16 terminals)

```
0–9   mid, spread, imbalance, volume, rsi, zscore, momentum, volatility, time_frac, prev_signal
10–13 do_imbalance, causal_mid, shock, confounder    ← causal / intervention
14–15 regime, regime_age                             ← regime indicators
```

---

## API Server — `artifacts/api-server/`

Express 5 + TypeScript. Proxies all `/api/genesis/*` requests to the Python engine on port 8000. Add new routes in `src/routes/genesis.ts`.

---

## Genesis Console — `artifacts/genesis-console/`

React 19 + Vite + Tailwind CSS + shadcn/ui. Dark terminal aesthetic (near-black, neon green/amber/red palette).

### Pages

| Route | What you see |
|-------|-------------|
| `/` Overview | P&L hero + live equity sparkline, dual-axis fitness/Sharpe chart, Population Landscape scatter (100 genomes by Sharpe tier), engine parameter sliders |
| `/market-making` | **Skew Helix** — sinusoidal bid/ask visualization driven by `GravityMarketMaker` inventory skew; inventory gauge; Reality Surface probability bars per market |
| `/strategies` | Hall-of-Fame strategy list with expression trees |
| `/safety` | Safety VM metrics |
| `/portfolio` | Capital composition donut, trades-by-outcome bar chart, curated strategy archive |
| `/audit` | Immutable audit trail viewer |

### Data flow

- `src/lib/store.tsx` polls `/api/genesis/*` every 1 s when the engine is running.
- `omega` field in store holds live data from `/api/genesis/omega-dashboard` (endpoint stub — returns `null` until wired on Python side; all charts fall back to synthetic live data automatically).
- All chart components in `src/components/charts/` ship with animated synthetic fallback data so the terminal always looks alive.

### Chart components

| Component | File |
|-----------|------|
| Equity sparkline + P&L hero | `EquityCurve.tsx` |
| GP population scatter | `PopulationLandscape.tsx` |
| Sinusoidal bid/ask helix | `SkewHelix.tsx` |
| Probability gauges per market | `RealitySurfacePanel.tsx` |

---

## Design rule

**Ship enforceable features.** Everything in `src/` compiles and runs. Architecture docs describe the full vision; the codebase delivers the measured, enforceable substrate that makes everything else possible.
