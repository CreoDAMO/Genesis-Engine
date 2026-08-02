const { proposed: followUps } = await proposeFollowUpTasks({
  tasks: [
    {
      title: "Wire the live exchange clients so the engine trades on real market data",
      category: "next_steps",
      description: `# Wire live exchange clients into the running engine
## What & Why
The Python engine ships with fully-implemented clients for Binance, Bybit, Deribit, and Polymarket (in \`artifacts/genesis-engine/src/api/\`), but the \`api_server.py\` only runs the genetic VM on synthetic data. Connecting live order-book feeds lets the engine evaluate strategies against real microstructure, not just noise.
## Done looks like
- \`api_server.py\` optionally loads exchange clients when API keys are present in \`config/config.yaml\`
- Live L2 order book data is fed into \`evolve()\` via the \`UnifiedOrderBook\` adapter in \`src/microstructure/orderbook.py\`
- The console's Strategies page shows real-market regime labels (not generation-count mod 3)
- Missing or invalid keys produce a clear error log; the engine falls back to synthetic mode gracefully
## Relevant files
- \`artifacts/genesis-engine/src/api_server.py\`
- \`artifacts/genesis-engine/src/api/binance_client.py\`, \`bybit_client.py\`, \`deribit_client.py\`, \`polymarket_client.py\`
- \`artifacts/genesis-engine/src/microstructure/orderbook.py\`
- \`artifacts/genesis-engine/config/config.yaml\`
- Secrets needed: BINANCE_API_KEY, BINANCE_API_SECRET, etc.`
    },
    {
      title: "Replace 1-second polling with a live WebSocket stream from the engine",
      category: "tech_debt",
      description: `# Replace polling with a WebSocket push from the Python engine
## What & Why
The React console polls \`/api/genesis/*\` once per second. For a fast evolution loop this creates lag, redundant network calls, and a stale-data window. A WebSocket connection lets the engine push each generation result instantly as it completes.
## Done looks like
- \`api_server.py\` exposes a \`/ws\` WebSocket endpoint that broadcasts each generation snapshot as JSON
- \`artifacts/genesis-console/src/lib/store.tsx\` replaces the \`setInterval\` polling loop with a \`useEffect\` WebSocket connection
- Chart and metric cards update in real time with no perceptible lag
- The \`engineAvailable\` flag flips to false on disconnect and recovers automatically on reconnect
## Relevant files
- \`artifacts/genesis-engine/src/api_server.py\` — add \`aiohttp\` WebSocket route
- \`artifacts/genesis-console/src/lib/store.tsx\` — replace polling with WebSocket hook`
    },
    {
      title: "Persist evolved strategies and audit logs to the PostgreSQL database",
      category: "next_steps",
      description: `# Save evolved strategies and audit logs to PostgreSQL
## What & Why
The Hall of Fame and audit trail currently live only in memory — they reset every time the Python engine restarts. Persisting them to the existing PostgreSQL + Drizzle setup means elite strategies survive restarts and the audit trail becomes a permanent compliance record.
## Done looks like
- \`lib/db/src/schema/\` has tables for \`strategies\` (id, expression, fitness, generation, dateAdded) and \`audit_logs\` (id, event, genomeId, fitness, timestamp, hash)
- The Python engine calls the Express API (or directly connects via pg) to persist each HOF promotion and audit event
- The Audit Trail and Portfolio pages in the console load from the database via existing React Query hooks
- \`pnpm --filter @workspace/db run push\` applies the new schema
## Relevant files
- \`lib/db/src/schema/index.ts\` — add strategy + audit_log tables
- \`lib/api-spec/openapi.yaml\` — add \`/strategies\` and \`/audit-logs\` endpoints
- \`artifacts/api-server/src/routes/\` — implement DB-backed route handlers
- \`artifacts/genesis-console/src/pages/Portfolio.tsx\`, \`Audit.tsx\`
- Required env: \`DATABASE_URL\``
    }
  ]
});
console.log("Follow-ups proposed:", followUps.map(t => t.taskRef + ": " + t.title));
await markTaskComplete({
  task_ref: "1",
  commit_message: "feat: integrate genesis_engine_v5_production.zip as a live Python service\n\n- Unpack engine to artifacts/genesis-engine/ (aiohttp REST API over genetic VM)\n- Wire Express /api/genesis/* proxy routes to Python engine\n- Update React console store to poll real engine instead of simulating client-side\n- Add ENGINE LIVE/OFFLINE indicator to ConsoleLayout header\n- Install Python 3.11 + aiohttp/numpy/websockets/pyyaml\n- Configure Genesis Engine (Python), API Server, and Genesis Console workflows\n- Update genesis-console port from 20153 to 5173 (workflow-supported)\n- Update replit.md with full stack documentation"
});
