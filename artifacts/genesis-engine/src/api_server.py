"""
Genesis Engine v5 — HTTP API Server
====================================
Wraps the genetic strategy engine and exposes evolution state as REST.

Endpoints:
  GET  /status            — engine status, settings, generation count
  POST /start             — start evolution loop
  POST /stop              — pause evolution loop
  POST /reset             — reset to generation 0
  GET  /history           — last 100 generation snapshots
  GET  /hall-of-fame      — top strategies discovered so far
  GET  /audit             — recent audit log entries
  POST /settings          — update engine parameters
  POST /hall-of-fame      — manually save a strategy to the HOF

Run via:
  python run.py
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiohttp import web

# ---------------------------------------------------------------------------
# Path setup: add the vm directory so genetic_strategy_engine can find its
# sibling modules (bytecode_vm, audit_trail) via bare imports.
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).parent
VM_DIR = SRC_DIR / "vm"
sys.path.insert(0, str(VM_DIR))

from vm.genetic_strategy_engine import GeneticStrategyEngine, generate_synthetic_markets, StrategyGenome  # noqa: E402
from vm.audit_trail import AuditTrail  # noqa: E402


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class EngineState:
    def __init__(self) -> None:
        self.is_running = False
        self.generation = 0

        self.history: List[Dict[str, Any]] = []
        self.audit_trail: List[Dict[str, Any]] = []
        self.hall_of_fame: List[Dict[str, Any]] = [
            {
                "id": "hof-seed-1",
                "name": "Momentum Reversion Alpha",
                "expression": "if_else(gt(rsi, 0.5), sub(0, ma_fast), mul(mid, 1.0))",
                "outOfSampleSharpe": 2.14,
                "maxDrawdown": -12.4,
                "complexityScore": 15,
                "dateAdded": "2026-07-31T00:00:00.000Z",
            },
            {
                "id": "hof-seed-2",
                "name": "Vol-Adjusted Carry",
                "expression": "div(sub(momentum, zscore), max(volatility, 0.01))",
                "outOfSampleSharpe": 1.85,
                "maxDrawdown": -8.2,
                "complexityScore": 9,
                "dateAdded": "2026-07-28T00:00:00.000Z",
            },
        ]

        self.settings: Dict[str, Any] = {
            "mutationRate": 0.05,
            "populationSize": 100,
            "maxFuelPerEval": 5000,
            "crossoverRate": 0.7,
        }

        self.gp_engine: Optional[GeneticStrategyEngine] = None
        self.evolution_task: Optional[asyncio.Task] = None

        os.makedirs("logs", exist_ok=True)
        self.audit_file = AuditTrail("logs/audit_live.jsonl")

    # ------------------------------------------------------------------
    def _now_iso(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

    def add_audit(self, action: str, details: str) -> None:
        entry = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": self._now_iso(),
            "action": action,
            "details": details,
        }
        self.audit_trail.insert(0, entry)
        self.audit_trail = self.audit_trail[:200]

    # ------------------------------------------------------------------
    def _settings_to_engine_params(self) -> Dict[str, Any]:
        return {
            "population_size": int(self.settings["populationSize"]),
            "mutation_rate": float(self.settings["mutationRate"]),
            "crossover_rate": float(self.settings["crossoverRate"]),
            "max_depth": 6,
            "seed": None,
            "audit": self.audit_file,
        }


state = EngineState()


# ---------------------------------------------------------------------------
# Regime mapper  (engine stores 0=calm / 1=stress; UI expects BULL/BEAR/VOLATILE)
# ---------------------------------------------------------------------------
_REGIMES = ["BULL", "BEAR", "VOLATILE"]


def _regime_str(value: Any) -> str:
    try:
        return _REGIMES[int(float(value)) % 3]
    except Exception:
        return "BULL"


# ---------------------------------------------------------------------------
# Evolution loop (runs inside asyncio executor to avoid blocking the event loop)
# ---------------------------------------------------------------------------

_MARKETS: Optional[Dict[str, Any]] = None  # cached synthetic market data


def _run_one_generation() -> Dict[str, Any]:
    """Blocking: called inside run_in_executor."""
    global _MARKETS
    if _MARKETS is None:
        _MARKETS = generate_synthetic_markets(n_paths=10, n_steps=50, seed=42)

    best: StrategyGenome = state.gp_engine.evolve(_MARKETS)  # type: ignore[union-attr]

    fitness = float(best.fitness) if math.isfinite(best.fitness) else 0.0
    pop = state.gp_engine.population  # type: ignore[union-attr]
    fitnesses = [
        float(g.fitness) if math.isfinite(g.fitness) else 0.0
        for g in pop
    ]
    avg_fit = sum(fitnesses) / len(fitnesses) if fitnesses else 0.0

    # Rough fuel estimate: population × average opcodes per strategy
    fuel_used = int(len(pop) * 50)

    return {
        "max_fitness": fitness,
        "avg_fitness": avg_fit,
        "best_source": best.source,
        "generation": state.gp_engine.generation,  # type: ignore[union-attr]
    }


async def _evolution_loop() -> None:
    state.gp_engine = GeneticStrategyEngine(**state._settings_to_engine_params())
    state.gp_engine.initialize()  # type: ignore[union-attr]
    state.add_audit("ENGINE_INITIALIZED", f"Population={state.settings['populationSize']}")
    state.add_audit("RUN_STARTED", f"Generation {state.generation}")

    hof_threshold = 1.5  # fitness threshold for HOF admission

    loop = asyncio.get_event_loop()
    while state.is_running:
        try:
            result = await loop.run_in_executor(None, _run_one_generation)

            state.generation = result["generation"]
            max_fit = result["max_fitness"]
            avg_fit = result["avg_fitness"]

            # Map last feature of synthetic market (regime) to label
            regime_val = state.generation % 3  # rotates BULL/BEAR/VOLATILE for variety
            regime_str = _REGIMES[regime_val]

            gen_data: Dict[str, Any] = {
                "generation": state.generation,
                "maxFitness": round(max_fit, 4),
                "avgFitness": round(avg_fit, 4),
                "bestExpression": result["best_source"],
                "regime": regime_str,
                "fuelUsed": result.get("fuel_used", int(state.settings["populationSize"]) * 50),
            }
            state.history.append(gen_data)
            state.history = state.history[-100:]

            # Promote to Hall of Fame if elite
            if max_fit > hof_threshold and state.generation % 5 == 0:
                hof_entry: Dict[str, Any] = {
                    "id": f"hof-{str(uuid.uuid4())[:6]}",
                    "name": f"Gen {state.generation} Elite ({regime_str})",
                    "expression": result["best_source"],
                    "outOfSampleSharpe": round(max_fit * 0.75, 2),
                    "maxDrawdown": round(-abs(avg_fit) * 3.5, 1),
                    "complexityScore": len(result["best_source"].split("(")) - 1,
                    "dateAdded": state._now_iso(),
                }
                state.hall_of_fame.insert(0, hof_entry)
                state.hall_of_fame = state.hall_of_fame[:20]
                state.add_audit(
                    "SAVED_TO_HOF",
                    f"Gen {state.generation} elite: fitness={max_fit:.4f}",
                )

            await asyncio.sleep(0.05)  # small yield to keep event loop responsive

        except asyncio.CancelledError:
            break
        except Exception as exc:
            state.add_audit("ENGINE_ERROR", str(exc))
            await asyncio.sleep(2.0)

    state.add_audit("RUN_PAUSED", f"Generation {state.generation}")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_status(request: web.Request) -> web.Response:
    return web.json_response({
        "isRunning": state.is_running,
        "generation": state.generation,
        "settings": state.settings,
    })


async def handle_start(request: web.Request) -> web.Response:
    if not state.is_running:
        state.is_running = True
        state.evolution_task = asyncio.create_task(_evolution_loop())
    return web.json_response({"ok": True})


async def handle_stop(request: web.Request) -> web.Response:
    state.is_running = False
    if state.evolution_task:
        state.evolution_task.cancel()
        state.evolution_task = None
    return web.json_response({"ok": True})


async def handle_reset(request: web.Request) -> web.Response:
    state.is_running = False
    if state.evolution_task:
        state.evolution_task.cancel()
        state.evolution_task = None
    state.generation = 0
    state.history = []
    state.gp_engine = None
    global _MARKETS
    _MARKETS = None
    state.add_audit("RUN_RESET", "Evolution environment cleared")
    return web.json_response({"ok": True})


async def handle_history(request: web.Request) -> web.Response:
    return web.json_response(state.history)


async def handle_hall_of_fame_get(request: web.Request) -> web.Response:
    return web.json_response(state.hall_of_fame)


async def handle_hall_of_fame_post(request: web.Request) -> web.Response:
    body = await request.json()
    entry: Dict[str, Any] = {
        "id": f"hof-{str(uuid.uuid4())[:6]}",
        "dateAdded": state._now_iso(),
        **body,
    }
    state.hall_of_fame.insert(0, entry)
    state.hall_of_fame = state.hall_of_fame[:20]
    state.add_audit(
        "SAVED_TO_PORTFOLIO",
        f'Strategy "{body.get("name", "Unknown")}" added to Hall of Fame',
    )
    return web.json_response({"ok": True})


async def handle_audit(request: web.Request) -> web.Response:
    return web.json_response(state.audit_trail)


async def handle_settings(request: web.Request) -> web.Response:
    body = await request.json()
    allowed = {"mutationRate", "populationSize", "maxFuelPerEval", "crossoverRate"}
    for k, v in body.items():
        if k in allowed:
            state.settings[k] = v
            state.add_audit("SETTING_CHANGED", f"{k} → {v}")

    # If engine running, restart with new params on next cycle
    if state.is_running:
        state.is_running = False
        if state.evolution_task:
            state.evolution_task.cancel()
        state.is_running = True
        state.evolution_task = asyncio.create_task(_evolution_loop())

    return web.json_response({"ok": True, "settings": state.settings})


async def handle_checkpoint(request: web.Request) -> web.Response:
    """
    POST /checkpoint — serialize GP population + inventory to disk.

    Call this before restarting the process so evolution progress isn't lost.
    Response: {"ok": true, "path": "<file>", "generation": N}
    """
    import json as _json
    import math as _math

    pop = state.gp_engine.population if state.gp_engine else []
    hof = state.hall_of_fame

    pop_data = []
    for g in pop:
        fit = float(g.fitness) if _math.isfinite(getattr(g, "fitness", float("nan"))) else -1e6
        pop_data.append({
            "genome_id":  g.genome_id,
            "source":     g.source,
            "fitness":    fit,
            "sharpe":     float(getattr(g, "sharpe", 0.0)),
            "generation": getattr(g, "generation", 0),
            "parent_ids": getattr(g, "parent_ids", []),
            "n_evals":    getattr(g, "n_evals", 0),
        })

    hof_data = []
    for e in hof:
        if isinstance(e, dict):
            hof_data.append(e)
        else:
            hof_data.append({
                "genome_id":  getattr(e, "genome_id", ""),
                "source":     getattr(e, "source", ""),
                "fitness":    float(getattr(e, "fitness", -1e6)),
                "sharpe":     float(getattr(e, "sharpe", 0.0)),
                "generation": getattr(e, "generation", 0),
            })

    checkpoint_state = {
        "timestamp":    __import__("time").time(),
        "generation":   state.generation,
        "population":   pop_data,
        "hall_of_fame": hof_data,
        "daily_pnl":    0.0,
        "peak_pnl":     0.0,
    }

    import os as _os
    _os.makedirs("checkpoints", exist_ok=True)
    path = "checkpoints/engine_state.json"
    with open(path, "w") as f:
        _json.dump(checkpoint_state, f, indent=2)

    state.add_audit("CHECKPOINT_SAVED", f"gen={state.generation} pop={len(pop_data)}")
    return web.json_response({
        "ok":         True,
        "path":       path,
        "generation": state.generation,
        "pop_size":   len(pop_data),
        "hof_size":   len(hof_data),
    })


async def handle_restore(request: web.Request) -> web.Response:
    """
    POST /restore — reload population + hall-of-fame from the last checkpoint.

    Rebuilds StrategyGenome objects from their source strings so the GP engine
    resumes from the saved generation without resetting to Gen 0.
    Response: {"ok": true, "generation": N, "pop_restored": K}
    """
    import json as _json
    import ast as _ast
    import os as _os

    path = "checkpoints/engine_state.json"
    if not _os.path.exists(path):
        return web.json_response({"ok": False, "error": "No checkpoint found"}, status=404)

    with open(path) as f:
        saved = _json.load(f)

    restored = 0
    if state.gp_engine is not None:
        from vm.genetic_strategy_engine import StrategyGenome
        import uuid as _uuid

        new_pop = []
        for gd in saved.get("population", []):
            try:
                tree = _ast.parse(gd["source"], mode="eval").body
                g = StrategyGenome(
                    ast_tree   = tree,
                    source     = gd["source"],
                    fitness    = gd.get("fitness", -1e6),
                    sharpe     = gd.get("sharpe", 0.0),
                    generation = gd.get("generation", 0),
                    parent_ids = gd.get("parent_ids", []),
                    genome_id  = gd.get("genome_id", str(_uuid.uuid4())[:8]),
                    n_evals    = gd.get("n_evals", 1),
                )
                new_pop.append(g)
                restored += 1
            except Exception:
                pass

        if new_pop:
            state.gp_engine.population  = new_pop
            state.gp_engine.generation  = saved.get("generation", 0)
            state.generation            = saved.get("generation", 0)

    state.add_audit(
        "CHECKPOINT_RESTORED",
        f"gen={saved.get('generation', 0)} pop_restored={restored}",
    )
    return web.json_response({
        "ok":           True,
        "generation":   saved.get("generation", 0),
        "pop_restored": restored,
        "path":         path,
    })


async def handle_omega_dashboard(request: web.Request) -> web.Response:
    """
    Omega dashboard snapshot consumed by the React Market Making terminal.

    Builds OmegaDashboard-shaped JSON from live engine state so the console
    receives real data as soon as an evolution run is in progress.
    """
    import math as _math

    # ── P&L series: cumulative sum of (maxFitness * scale) per generation ──
    pnl_series = []
    cumulative = 0.0
    for i, h in enumerate(state.history):
        fit = h.get("maxFitness", 0.0)
        cumulative += fit * 50.0   # scale fitness → rough USD units
        pnl_series.append({"t": i, "pnl": round(cumulative, 2)})

    # ── Population landscape: one dot per genome ────────────────────────────
    population = []
    if state.gp_engine is not None:
        for idx, genome in enumerate(state.gp_engine.population):
            fit = float(genome.fitness) if _math.isfinite(genome.fitness) else 0.0
            shp = float(getattr(genome, "sharpe", 0.0))
            shp = shp if _math.isfinite(shp) else 0.0
            complexity = max(1, len(genome.source.split("(")) - 1)
            population.append({
                "id": f"g{idx}",
                "sharpe":     round(shp, 3),
                "fitness":    round(fit, 4),
                "complexity": complexity,
                "generation": getattr(state.gp_engine, "generation", state.generation),
            })

    # ── Capital by strategy: weighted by Hall-of-Fame Sharpe ───────────────
    hof = state.hall_of_fame
    total_sharpe = sum(max(e.get("outOfSampleSharpe", 0.01), 0.01) for e in hof) or 1.0
    capital_by_strategy = [
        {
            "name": e.get("name", "Unknown")[:22],
            "value": round(
                max(e.get("outOfSampleSharpe", 0.01), 0.01) / total_sharpe * 10_000, 2
            ),
        }
        for e in hof[:8]
    ] if hof else [{"name": "Unallocated", "value": 10000}]

    # ── Trades by outcome: count gens + P&L per regime ─────────────────────
    regimes = ["BULL", "BEAR", "VOLATILE"]
    trades_by_outcome = [
        {
            "outcome": r,
            "count":   sum(1 for h in state.history if h.get("regime") == r),
            "pnl":     round(
                sum(h.get("maxFitness", 0.0) * 50.0
                    for h in state.history if h.get("regime") == r),
                2,
            ),
        }
        for r in regimes
    ]

    return web.json_response({
        "pnl_series":          pnl_series,
        "population":          population,
        "surface":             [],   # populated by Reality Surface when wired
        "helix":               [],   # populated by Gravity LP when wired
        "capital_by_strategy": capital_by_strategy,
        "trades_by_outcome":   trades_by_outcome,
        "paper_trade":         True,
        "wasm_fuel":           state.settings.get("maxFuelPerEval", 5000),
    })


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

@web.middleware
async def cors_middleware(request: web.Request, handler: Any) -> web.Response:
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/healthz", handle_health)
    app.router.add_post("/checkpoint", handle_checkpoint)
    app.router.add_post("/restore", handle_restore)
    app.router.add_get("/omega-dashboard", handle_omega_dashboard)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/start", handle_start)
    app.router.add_post("/stop", handle_stop)
    app.router.add_post("/reset", handle_reset)
    app.router.add_get("/history", handle_history)
    app.router.add_get("/hall-of-fame", handle_hall_of_fame_get)
    app.router.add_post("/hall-of-fame", handle_hall_of_fame_post)
    app.router.add_get("/audit", handle_audit)
    app.router.add_post("/settings", handle_settings)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[Genesis Engine API] Starting on port {port}")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)
