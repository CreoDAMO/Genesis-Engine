# Genesis Strategy Console

An evolutionary trading strategy research platform. The **Python engine** evolves expression-tree strategies using a fuel-metered bytecode VM and genetic programming. The **React console** visualises fitness convergence, regime shifts, portfolio metrics, and an immutable audit trail in real time.

## Run & Operate

Three services must all be running:

| Service | Workflow | Port |
|---------|----------|------|
| Genesis Engine (Python) | `Genesis Engine (Python)` | 8000 |
| Express API Server | `API Server` | 8080 |
| React Console (Vite) | `Genesis Console` | 5173 |

- `pnpm install` — install all workspace dependencies
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string (needed only when DB features are used)

## Stack

- pnpm workspaces, Node.js 20, TypeScript 5.9
- **Frontend:** React + Vite + Tailwind CSS + shadcn/ui (artifacts/genesis-console)
- **API proxy:** Express 5 (artifacts/api-server) — routes `/api/genesis/*` to the Python engine
- **Python engine:** aiohttp + numpy (artifacts/genesis-engine) — genetic strategy VM
- DB: PostgreSQL + Drizzle ORM (lib/db) — not yet wired up to the engine
- API codegen: Orval (from OpenAPI spec in lib/api-spec)

## Where things live

- `artifacts/genesis-console/src/lib/store.tsx` — React state store; polls Python engine every 1 s
- `artifacts/genesis-console/src/pages/` — Overview, Strategies, Safety, Portfolio, Audit pages
- `artifacts/genesis-engine/src/api_server.py` — aiohttp REST wrapper around the genetic engine
- `artifacts/genesis-engine/src/vm/genetic_strategy_engine.py` — core GP engine (evolve, crossover, mutate)
- `artifacts/genesis-engine/src/vm/bytecode_vm.py` — fuel-metered bytecode VM (containment boundary)
- `artifacts/genesis-engine/run.py` — Python entry point (sets sys.path, starts aiohttp)
- `artifacts/api-server/src/routes/genesis.ts` — Express proxy routes for `/api/genesis/*`
- `lib/api-spec/openapi.yaml` — OpenAPI spec (source of truth for all typed API contracts)

## Architecture decisions

- The Python engine is a standalone aiohttp service; Express proxies to it rather than embedding Python in Node.
- The React store polls `/api/genesis/*` every 1 s when the engine is running; no WebSocket needed yet.
- `engineAvailable` flag in the store turns the header badge green/grey based on reachability.
- Exchange API clients (Binance, Bybit, Deribit, Polymarket) and swarm infra (Redis, Neo4j) are present in the engine source but not started — the engine runs in genetic-VM-only mode by default.
- LLM strategy invention (`strategies/llm_invention.py`) requires `OPENAI_API_KEY` in config/config.yaml.

## Product

Users open the console, click **START RUN**, and watch the genetic algorithm evolve trading strategies across simulated regime-shifting markets. Each generation's best expression tree, fitness score (Sharpe × Calmar × WinRate), fuel usage, and market regime are streamed into charts and tables. Elite strategies auto-promote to the Hall of Fame.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- `genetic_strategy_engine.py` uses bare imports (`from bytecode_vm import ...`). `run.py` inserts `src/vm/` onto `sys.path` before importing, so always start via `python run.py` from `artifacts/genesis-engine/`, not directly.
- The `Genesis Console` and `API Server` workflows must be running for the browser UI to show "ENGINE LIVE"; the Python engine must also be running for evolution to work.
- Port 20153 (original genesis-console port) is not in configureWorkflow's supported list; the artifact.toml and workflow both now use port 5173.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
- Full v5 architecture doc: `artifacts/genesis-engine/ARCHITECTURE_v5.0.md`
