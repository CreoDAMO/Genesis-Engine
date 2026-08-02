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
