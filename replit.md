# Genesis Strategy Console

An evolutionary trading-strategy research platform. The **Python engine** evolves expression-tree strategies using a fuel-metered bytecode VM and genetic programming. The **React console** visualises fitness convergence, market-making state, population landscape, and an immutable audit trail in real time.

## Run & Operate

Three services run as artifact-managed workflows:

| Service | Workflow name | Default port |
|---------|---------------|-------------|
| Genesis Engine (Python) | `Genesis Engine (Python)` | 8000 |
| Express API Server | `artifacts/api-server: API Server` | 8080 |
| React Console (Vite) | `artifacts/genesis-console: web` | assigned by platform |

```bash
pnpm install                        # install all workspace deps
pip install -r artifacts/genesis-engine/requirements.txt   # Python deps
```

```bash
pnpm run typecheck                  # full typecheck across all packages
pnpm run build                      # typecheck + build all packages
pnpm --filter @workspace/api-spec run codegen   # regenerate API hooks from OpenAPI spec
```

## Stack

- pnpm workspaces, Node.js 20, TypeScript 5.9
- **Frontend:** React 19 + Vite + Tailwind CSS v4 + shadcn/ui (`artifacts/genesis-console`)
- **API proxy:** Express 5 (`artifacts/api-server`) — routes `/api/genesis/*` to the Python engine
- **Python engine:** aiohttp + numpy (`artifacts/genesis-engine`) — genetic strategy VM + v6 Omega modules
- DB: PostgreSQL + Drizzle ORM (`lib/db`) — schema present, not yet wired to the engine
- API codegen: Orval (from OpenAPI spec in `lib/api-spec/`)

## Where things live

**Console (React)**
- `artifacts/genesis-console/src/lib/store.tsx` — state store; polls Python engine every 1 s; holds `omega` data when `/omega-dashboard` responds
- `artifacts/genesis-console/src/pages/Overview.tsx` — P&L hero, equity sparkline, fitness/Sharpe dual-axis chart, population landscape scatter, engine parameters
- `artifacts/genesis-console/src/pages/MarketMaking.tsx` — Skew Helix, inventory gauge, Reality Surface probability bars
- `artifacts/genesis-console/src/pages/Portfolio.tsx` — capital donut, trades-by-outcome bars, Hall of Fame list
- `artifacts/genesis-console/src/components/charts/` — SkewHelix, PopulationLandscape, RealitySurfacePanel, EquityCurve (all with synthetic live fallback)
- `artifacts/genesis-console/src/lib/colors.ts` — neon hex palette constants (`#00ff88`, `#ffaa00`, `#ff3366`, `#00d4ff`)

**API Server (Express)**
- `artifacts/api-server/src/routes/genesis.ts` — proxy routes for `/api/genesis/*`

**Python engine**
- `artifacts/genesis-engine/run.py` — entry point; sets `sys.path`, starts `src/api_server.py` on port 8000
- `artifacts/genesis-engine/omega_engine.py` — v6 orchestrator (5 async loops); start standalone with `python omega_engine.py`
- `artifacts/genesis-engine/src/api_server.py` — aiohttp REST wrapper
- `artifacts/genesis-engine/src/vm/genetic_strategy_engine.py` — core GP engine (evolve, crossover, mutate, Sharpe-first selection)
- `artifacts/genesis-engine/src/vm/bytecode_vm.py` — fuel-metered VM (NaN-propagating SafeMath in v6)
- `artifacts/genesis-engine/src/patches/` — v6 safety: SafeMath, FitnessGate, AuditSanitizer, LexicographicSelector
- `artifacts/genesis-engine/src/reality_surface/claim_normalizer.py` — cross-venue probability consensus
- `artifacts/genesis-engine/src/gravity/lp_dominance.py` — inventory-skewed CLOB market making
- `artifacts/genesis-engine/src/sandbox/wasm_compiler.py` — WASM strategy execution (SafePythonVM fallback)

**Shared**
- `lib/api-spec/openapi.yaml` — OpenAPI spec (source of truth for all typed contracts)
- `lib/db/` — Drizzle ORM schema for PostgreSQL

## Architecture decisions

- The Python engine is a standalone aiohttp service; Express proxies to it rather than embedding Python in Node.
- The React store polls `/api/genesis/*` every 1 s; no WebSocket needed yet.
- `engineAvailable` flag in the store turns the header badge green/grey based on reachability.
- All chart components carry animated synthetic fallback data so the console looks live even when the engine is offline or `omega-dashboard` isn't wired yet.
- SVG colour values use hex constants (`#00ff88` etc.) rather than `var(--neon-green)` — SVG presentation attributes do not resolve CSS custom properties; only `style={}` props do.
- Exchange API clients and swarm infra (Redis, Neo4j) are present in the engine source but not started — engine runs in GP-VM-only mode by default.
- The `omega_engine.py` orchestrator starts in `paper_trade=True` mode. Set `PAPER_TRADE=false` only after weeks of validation.

## What still needs wiring

| Item | Where |
|------|-------|
| `omega_engine.py` stubs | Plug in `polymarket_client`, `deribit_client`, `gp_engine` (code is commented-out and ready) |
| `/omega-dashboard` API endpoint | Add to `src/api_server.py` + proxy in `api-server/src/routes/genesis.ts` |
| AST → WASM code generator | `src/sandbox/wasm_compiler.py` `_ast_to_wat()` needs full expression-tree walk |
| PostgreSQL persistence | `lib/db/` schema + Drizzle not yet wired to engine |

## Gotchas

- `genetic_strategy_engine.py` uses bare imports (`from bytecode_vm import ...`). Always start via `python run.py` from `artifacts/genesis-engine/` — `run.py` inserts `src/vm/` onto `sys.path` first.
- Use artifact-managed workflows (`artifacts/genesis-console: web`, `artifacts/api-server: API Server`). Do **not** recreate manually-configured workflows on the same ports — they collide.
- The v6 patch modules in `src/patches/` must be on `sys.path`. The path injection at the top of `genetic_strategy_engine.py` handles this automatically.
- `wasmtime` not installed by default — `wasm_compiler.py` falls back to `SafePythonVM`. Run `pip install wasmtime` and add to `requirements.txt` to enable WASM execution.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._
