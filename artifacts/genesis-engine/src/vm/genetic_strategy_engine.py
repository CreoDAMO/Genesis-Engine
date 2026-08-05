"""
Genesis Engine — Autopoietic Strategy Genesis Core
====================================================
Genetic programming engine that evolves trading strategies as expression trees,
compiles them to bytecode, and evaluates them inside the fuel-metered VM.

Includes:
  - Random tree generation with causal / regime-aware terminals
  - Crossover, mutation, elitism
  - Fitness = Sharpe × Calmar × WinRate (with Occam penalty)
  - Synthetic market generator with regime shifts and causal DAG
"""

from __future__ import annotations

import ast
import random
import copy
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any, Optional
import numpy as np

from bytecode_vm import compile_ast, execute, MAX_FUEL, FEATURE_INDEX
from audit_trail import AuditTrail

# v6 patches: fitness gating, audit sanitization, Sharpe-first selection
import sys as _sys
import os as _os
_patches_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "patches")
if _patches_dir not in _sys.path:
    _sys.path.insert(0, _patches_dir)
try:
    from vm_hardening_patch import FitnessGate as _FitnessGate, AuditSanitizer as _AuditSanitizer
    _V6_HARDENING = True
except ImportError:
    _V6_HARDENING = False

# ---------------------------------------------------------------------------
# Feature keys (must stay in sync with FEATURE_INDEX in bytecode_vm.py)
# ---------------------------------------------------------------------------
FEATURE_KEYS = [
    "mid", "spread", "imbalance", "volume", "rsi",
    "zscore", "momentum", "volatility", "time_frac", "prev_signal",
    "do_imbalance", "causal_mid", "shock", "confounder",
    "regime", "regime_age",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _sharpe(returns: np.ndarray) -> float:
    std = float(np.std(returns)) + 1e-12
    return float(np.mean(returns)) / std * np.sqrt(252)


def _calmar(returns: np.ndarray) -> float:
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / (peak + 1e-12)
    max_dd = float(np.max(dd))
    if max_dd < 1e-6:
        return 1e6
    return float(np.mean(returns)) * np.sqrt(252) / max_dd


def _winrate(returns: np.ndarray) -> float:
    wins = np.sum(returns > 0)
    n = len(returns)
    return wins / n if n > 0 else 0.5


# ---------------------------------------------------------------------------
# Genome
# ---------------------------------------------------------------------------

@dataclass
class StrategyGenome:
    """A strategy is an AST + metadata."""
    ast_tree: ast.AST
    source: str
    fitness: float = -np.inf
    sharpe: float = 0.0          # v6: stored separately for Sharpe-first selection
    generation: int = 0
    parent_ids: List[str] = field(default_factory=list)
    genome_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    n_evals: int = 0


# ---------------------------------------------------------------------------
# Synthetic market generator with causal DAG + regime shifts
# ---------------------------------------------------------------------------

def generate_synthetic_markets(
    n_paths: int = 20,
    n_steps: int = 100,
    seed: Optional[int] = None,
) -> Dict[str, np.ndarray]:
    """
    Generate synthetic market paths with:
      - Regime switching (calm ↔ stress)
      - Causal DAG: confounder → imbalance → mid, shock → imbalance
      - do(imbalance) intervention signal
    """
    rng = np.random.default_rng(seed)

    # Regime process: calm (0) vs stress (1)
    regime = np.zeros((n_paths, n_steps), dtype=float)
    regime_age = np.zeros((n_paths, n_steps), dtype=float)
    for p in range(n_paths):
        state = 0
        age = 0
        for t in range(n_steps):
            # Switch with small prob
            if rng.random() < 0.03:
                state = 1 - state
                age = 0
            else:
                age += 1
            regime[p, t] = state
            regime_age[p, t] = age

    # Confounder (common cause)
    confounder = rng.normal(0, 1, (n_paths, n_steps))

    # Shock intensity (higher in stress regime)
    shock = rng.exponential(0.5, (n_paths, n_steps)) * (1.0 + regime * 2.0)

    # Imbalance: driven by confounder + shock + noise
    imbalance = (
        0.4 * confounder
        + 0.3 * shock
        + rng.normal(0, 0.5, (n_paths, n_steps))
    )

    # do(imbalance): interventional version (what if we set imbalance to mean)
    do_imbalance = np.full_like(imbalance, float(np.mean(imbalance)))

    # Mid price: random walk + mean-reversion from imbalance
    mid = np.zeros((n_paths, n_steps))
    mid[:, 0] = 100.0 + rng.normal(0, 2, n_paths)
    for t in range(1, n_steps):
        ret = (
            0.02 * imbalance[:, t - 1]
            + rng.normal(0, 0.3 + 0.4 * regime[:, t], n_paths)
        )
        mid[:, t] = mid[:, t - 1] + ret

    # Causal mid: estimated mid under do(imbalance=0) — simplified
    causal_mid = mid - 0.02 * imbalance

    # Derived features
    spread = np.abs(rng.exponential(0.05, (n_paths, n_steps))) + 0.01
    volume = rng.lognormal(0, 1, (n_paths, n_steps))

    # RSI-like (simplified)
    rsi = 50.0 + 20.0 * np.tanh(imbalance)

    # Z-score of imbalance
    zscore = (imbalance - np.mean(imbalance, axis=1, keepdims=True)) / (
        np.std(imbalance, axis=1, keepdims=True) + 1e-12
    )

    # Momentum
    momentum = np.zeros_like(mid)
    momentum[:, 1:] = mid[:, 1:] - mid[:, :-1]

    # Volatility (rolling, simplified)
    volatility = np.zeros_like(mid)
    for t in range(5, n_steps):
        volatility[:, t] = np.std(momentum[:, t - 5:t], axis=1)
    volatility[:, :5] = volatility[:, 5:6]

    return {
        "mid": mid,
        "spread": spread,
        "imbalance": imbalance,
        "volume": volume,
        "rsi": rsi,
        "zscore": zscore,
        "momentum": momentum,
        "volatility": volatility,
        "do_imbalance": do_imbalance,
        "causal_mid": causal_mid,
        "shock": shock,
        "confounder": confounder,
        "regime": regime,
        "regime_age": regime_age,
    }


# ---------------------------------------------------------------------------
# Genetic Strategy Engine
# ---------------------------------------------------------------------------

class GeneticStrategyEngine:
    """
    Evolves trading strategies via genetic programming.
    Each strategy is a Python expression AST that compiles to bytecode.
    """

    TERMINALS = [
        "mid", "spread", "imbalance", "volume", "rsi",
        "zscore", "momentum", "volatility", "time_frac", "prev_signal",
        "do_imbalance", "causal_mid", "shock", "confounder",
        "regime", "regime_age",
    ]

    FUNCTIONS = [
        "add", "sub", "mul", "div", "max", "min", "gt", "lt",
        "neg", "abs", "log", "exp", "clip", "sign", "if_else",
    ]

    CONSTANTS = [-1.0, -0.5, 0.0, 0.5, 1.0, 2.0]

    def __init__(
        self,
        population_size: int = 100,
        mutation_rate: float = 0.3,
        crossover_rate: float = 0.7,
        elitism_count: int = 5,
        max_depth: int = 6,
        seed: Optional[int] = None,
        audit: Optional[AuditTrail] = None,
    ):
        self.pop_size = population_size
        self.mut_rate = mutation_rate
        self.cross_rate = crossover_rate
        self.elitism = elitism_count
        self.max_depth = max_depth
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.audit = audit

        self.population: List[StrategyGenome] = []
        self.generation = 0
        self.hall_of_fame: List[StrategyGenome] = []

    # -----------------------------------------------------------------------
    # Tree generation
    # -----------------------------------------------------------------------

    def _random_terminal(self) -> ast.AST:
        choice = self.rng.choice(self.TERMINALS + self.CONSTANTS)
        if isinstance(choice, str):
            return ast.Name(id=choice, ctx=ast.Load())
        return ast.Constant(value=choice)

    def _random_function_node(self, depth: int) -> ast.AST:
        fname = self.rng.choice(self.FUNCTIONS)

        if fname == "if_else":
            return ast.Call(
                func=ast.Name(id="if_else", ctx=ast.Load()),
                args=[
                    self._grow_tree(depth + 1),
                    self._grow_tree(depth + 1),
                    self._grow_tree(depth + 1),
                ],
                keywords=[],
            )
        elif fname in ("neg", "abs", "log", "exp", "clip", "sign"):
            return ast.Call(
                func=ast.Name(id=fname, ctx=ast.Load()),
                args=[self._grow_tree(depth + 1)],
                keywords=[],
            )
        else:
            return ast.Call(
                func=ast.Name(id=fname, ctx=ast.Load()),
                args=[self._grow_tree(depth + 1), self._grow_tree(depth + 1)],
                keywords=[],
            )

    def _grow_tree(self, depth: int = 0) -> ast.AST:
        if depth >= self.max_depth or (depth > 1 and self.rng.random() < 0.4):
            return self._random_terminal()
        return self._random_function_node(depth)

    # -----------------------------------------------------------------------
    # Population init
    # -----------------------------------------------------------------------

    def initialize(self):
        self.population = []
        for _ in range(self.pop_size):
            tree = self._grow_tree()
            source = ast.unparse(tree)
            self.population.append(
                StrategyGenome(ast_tree=tree, source=source, generation=0)
            )

    # -----------------------------------------------------------------------
    # Evaluation
    # -----------------------------------------------------------------------

    def _feature_vector(
        self,
        market_data: Dict[str, np.ndarray],
        p: int,
        t: int,
        prev_sig: float,
        n_steps: int,
    ) -> List[float]:
        return [
            float(market_data["mid"][p, t]),
            float(market_data["spread"][p, t]),
            float(market_data["imbalance"][p, t]),
            float(market_data["volume"][p, t]),
            float(market_data["rsi"][p, t]),
            float(market_data["zscore"][p, t]),
            float(market_data["momentum"][p, t]),
            float(market_data["volatility"][p, t]),
            float(t / max(n_steps - 1, 1)),
            prev_sig,
            float(market_data["do_imbalance"][p, t]),
            float(market_data["causal_mid"][p, t]),
            float(market_data["shock"][p, t]),
            float(market_data["confounder"][p, t]),
            float(market_data["regime"][p, t]),
            float(market_data["regime_age"][p, t]),
        ]

    def evaluate(
        self,
        genome: StrategyGenome,
        market_data: Dict[str, np.ndarray],
    ) -> float:
        """
        Evaluate a genome on synthetic market data.
        Returns fitness (Sharpe × Calmar × WinRate × Occam penalty).
        """
        if genome.fitness != -np.inf:
            return genome.fitness

        try:
            cs = compile_ast(genome.ast_tree, genome.source)
        except Exception:
            genome.fitness = -1e6
            return genome.fitness

        n_paths, n_steps = market_data["mid"].shape
        path_returns = []

        for p in range(n_paths):
            prev_sig = 0.0
            step_rets = []
            for t in range(n_steps - 1):
                feats = self._feature_vector(market_data, p, t, prev_sig, n_steps)
                try:
                    raw = execute(cs, feats, max_fuel=MAX_FUEL)
                    sig = _clip(float(raw))
                except Exception:
                    sig = 0.0

                ret = float(market_data["mid"][p, t + 1] - market_data["mid"][p, t])
                cost = 0.0008 * abs(sig - prev_sig)
                pnl = sig * ret - cost
                step_rets.append(pnl)
                prev_sig = sig

            path_returns.append(float(np.sum(step_rets)))

        returns = np.array(path_returns)

        if np.std(returns) < 1e-9:
            genome.fitness = -1e6
            return genome.fitness

        sharpe = _sharpe(returns)
        calmar = _calmar(returns)
        winrate = _winrate(returns)

        # Occam penalty: smaller trees preferred
        occam = 1.0 / (1.0 + cs.n_ops * 0.01)

        raw_fitness = sharpe * max(0, calmar) * winrate * occam

        # v6 hardening: gate fitness through FitnessGate (caps at ±1000, kills NaN,
        # rejects positive fitness with negative Sharpe)
        if _V6_HARDENING:
            fitness, sharpe, valid, reason = _FitnessGate.gate(raw_fitness, sharpe, returns)
            if not valid:
                genome.fitness = -1e6
                genome.sharpe = sharpe
                return genome.fitness
        else:
            fitness = raw_fitness

        genome.fitness = fitness
        genome.sharpe = sharpe
        genome.n_evals += 1

        # Audit trail
        if self.audit is not None:
            import hashlib
            bytecode_hash = hashlib.sha256(cs.code).hexdigest()[:16]
            audit_record = dict(
                event="EVAL",
                genome_id=genome.genome_id,
                source=genome.source,
                bytecode_hash=bytecode_hash,
                n_ops=cs.n_ops,
                fitness=fitness,
                sharpe=round(sharpe, 4),
                fuel_limit=MAX_FUEL,
                # v6 hardening probe: confirms which FitnessGate code is running.
                # If _fitness_cap is 'DISABLED' or 'MISSING' but |fitness| > 1000,
                # the live process loaded stale bytecode and must be restarted.
                _fitness_cap=(
                    getattr(_FitnessGate, "MAX_FITNESS", "MISSING")
                    if _V6_HARDENING else "DISABLED"
                ),
                extra={"generation": genome.generation},
            )
            # v6 hardening: sanitize before writing to chain
            if _V6_HARDENING:
                audit_record = _AuditSanitizer.sanitize(audit_record)
            self.audit.log(**{k: v for k, v in audit_record.items() if k != "extra"},
                           extra=audit_record.get("extra", {}))

        return fitness

    # -----------------------------------------------------------------------
    # Genetic operators
    # -----------------------------------------------------------------------

    def _pick_parent(self) -> StrategyGenome:
        """
        Tournament selection (size 3) — v6: Sharpe-first lexicographic ranking.

        Prevents fitness-explosion clones from winning: a strategy with
        fitness=11M but Sharpe=-5.88 will never be selected over one with
        fitness=0.8 and Sharpe=1.2.
        """
        candidates = self.rng.sample(self.population, min(3, len(self.population)))

        # Split into viable (positive Sharpe) and fallback
        viable = [c for c in candidates if c.sharpe > 0.0]
        pool = viable if viable else candidates

        # Lexicographic: Sharpe desc, then fitness desc
        return max(pool, key=lambda g: (g.sharpe, g.fitness))

    def _mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """Point mutation: replace a random subtree."""
        tree = copy.deepcopy(genome.ast_tree)

        def mutate_node(node: ast.AST, depth: int = 0) -> ast.AST:
            if depth > self.max_depth:
                return self._random_terminal()
            if self.rng.random() < self.mut_rate:
                return self._grow_tree(depth)
            if isinstance(node, ast.Call):
                new_args = [mutate_node(arg, depth + 1) for arg in node.args]
                node.args = new_args
            elif isinstance(node, ast.BinOp):
                node.left = mutate_node(node.left, depth + 1)
                node.right = mutate_node(node.right, depth + 1)
            elif isinstance(node, ast.UnaryOp):
                node.operand = mutate_node(node.operand, depth + 1)
            return node

        new_tree = mutate_node(tree)
        source = ast.unparse(new_tree)
        return StrategyGenome(
            ast_tree=new_tree,
            source=source,
            generation=self.generation,
            parent_ids=[genome.genome_id],
        )

    def _crossover(
        self, a: StrategyGenome, b: StrategyGenome
    ) -> StrategyGenome:
        """Subtree crossover."""
        tree_a = copy.deepcopy(a.ast_tree)
        tree_b = copy.deepcopy(b.ast_tree)

        def collect_subtrees(node: ast.AST, depth: int = 0) -> List[ast.AST]:
            nodes = [node]
            if isinstance(node, ast.Call):
                for arg in node.args:
                    nodes.extend(collect_subtrees(arg, depth + 1))
            elif isinstance(node, ast.BinOp):
                nodes.extend(collect_subtrees(node.left, depth + 1))
                nodes.extend(collect_subtrees(node.right, depth + 1))
            elif isinstance(node, ast.UnaryOp):
                nodes.extend(collect_subtrees(node.operand, depth + 1))
            return nodes

        def replace_subtree(
            node: ast.AST, target: ast.AST, replacement: ast.AST
        ) -> ast.AST:
            if node is target:
                return replacement
            if isinstance(node, ast.Call):
                node.args = [
                    replace_subtree(arg, target, replacement) for arg in node.args
                ]
            elif isinstance(node, ast.BinOp):
                node.left = replace_subtree(node.left, target, replacement)
                node.right = replace_subtree(node.right, target, replacement)
            elif isinstance(node, ast.UnaryOp):
                node.operand = replace_subtree(node.operand, target, replacement)
            return node

        subtrees_a = collect_subtrees(tree_a)
        subtrees_b = collect_subtrees(tree_b)

        if not subtrees_a or not subtrees_b:
            return copy.deepcopy(a)

        target = self.rng.choice(subtrees_a)
        donor = self.rng.choice(subtrees_b)
        new_tree = replace_subtree(tree_a, target, copy.deepcopy(donor))
        source = ast.unparse(new_tree)
        return StrategyGenome(
            ast_tree=new_tree,
            source=source,
            generation=self.generation,
            parent_ids=[a.genome_id, b.genome_id],
        )

    # -----------------------------------------------------------------------
    # Evolution step
    # -----------------------------------------------------------------------

    def evolve(self, market_data: Dict[str, np.ndarray]) -> StrategyGenome:
        """
        Run one generation: evaluate, select, breed, replace.

        v6 improvements:
          - NaN fitness guard before sort (prevents undefined sort behavior)
          - Sharpe-first elitism (top performers selected by Sharpe, then fitness)
          - Diversity tracking: log unique sources / population size each generation
          - Periodic re-seeding: inject 15% random genomes every 5 generations
            or when diversity drops below 85%
        """
        # Evaluate all
        for g in self.population:
            self.evaluate(g, market_data)

        # v6: NaN guard — replace any NaN/Inf fitness with floor before sorting
        for g in self.population:
            if not (g.fitness == g.fitness) or g.fitness == float("inf"):  # isnan or isinf
                g.fitness = -1e6
                g.sharpe = -5.0

        # v6: Sharpe-first elitism — sort by (sharpe, fitness) not just fitness.
        # This prevents numerically explosive strategies from surviving as elites.
        self.population.sort(key=lambda g: (g.sharpe, g.fitness), reverse=True)

        # Update hall of fame (also Sharpe-first)
        for g in self.population[:self.elitism]:
            if not any(h.genome_id == g.genome_id for h in self.hall_of_fame):
                self.hall_of_fame.append(copy.deepcopy(g))
        self.hall_of_fame.sort(key=lambda g: (g.sharpe, g.fitness), reverse=True)
        self.hall_of_fame = self.hall_of_fame[:20]

        # v6: Diversity tracking
        unique_sources = len(set(g.source for g in self.population))
        diversity = unique_sources / len(self.population) if self.population else 0

        # v6: Periodic re-seeding when diversity is low or every 5 generations
        should_reseed = diversity < 0.85 or (self.generation > 0 and self.generation % 5 == 0)
        if should_reseed:
            n_seed = max(1, int(self.pop_size * 0.15))
            # Keep elites + top survivors; replace bottom 15% with fresh random genomes
            survivors = self.population[: self.pop_size - n_seed]
            seeds = []
            for _ in range(n_seed):
                tree = self._grow_tree()
                seeds.append(StrategyGenome(ast_tree=tree, source=ast.unparse(tree), generation=self.generation))
            self.population = survivors + seeds

        # Elites survive
        new_pop = [copy.deepcopy(g) for g in self.population[:self.elitism]]

        # Breed rest
        while len(new_pop) < self.pop_size:
            if self.rng.random() < self.cross_rate:
                p1 = self._pick_parent()
                p2 = self._pick_parent()
                child = self._crossover(p1, p2)
            else:
                parent = self._pick_parent()
                child = self._mutate(parent)
            new_pop.append(child)

        self.population = new_pop
        self.generation += 1

        best = self.population[0]
        import logging as _logging
        _logging.getLogger("genesis.gp").info(
            f"[Gen {self.generation:3d}] "
            f"best_sharpe={best.sharpe:6.3f} best_fit={best.fitness:8.4f} | "
            f"diversity={diversity:.1%} ({unique_sources}/{self.pop_size}) "
            f"reseeded={should_reseed}"
        )
        return best


# ---------------------------------------------------------------------------
# Demo / CLI
# ---------------------------------------------------------------------------

def main():
    print("=" * 72)
    print("Genesis Engine v5.0-alpha — Autopoietic Strategy Genesis Demo")
    print("=" * 72)

    audit = AuditTrail("audit_log.jsonl")
    engine = GeneticStrategyEngine(
        population_size=40,
        max_depth=5,
        seed=42,
        audit=audit,
    )
    engine.initialize()

    data = generate_synthetic_markets(n_paths=20, n_steps=100, seed=7)

    print(f"\nSynthetic market: {data['mid'].shape[0]} paths × {data['mid'].shape[1]} steps")
    print(f"Regime switches: calm={np.sum(data['regime']==0)}  stress={np.sum(data['regime']==1)}")

    n_gens = 10
    for gen in range(n_gens):
        best = engine.evolve(data)
        print(
            f"Gen {gen:2d} | best fit={best.fitness:8.4f} | "
            f"source={best.source[:60]}..."
        )

    print(f"\nHall of Fame ({len(engine.hall_of_fame)} strategies):")
    for i, g in enumerate(engine.hall_of_fame[:5]):
        print(f"  {i+1}. fit={g.fitness:8.4f} | {g.source[:70]}")

    # Portfolio evaluation
    from portfolio import evaluate_portfolio
    port_metrics = evaluate_portfolio(engine.hall_of_fame[:8], data)
    print(f"\nPortfolio (top 8 HOF):")
    for k, v in port_metrics.items():
        print(f"  {k:12s}: {v:.4f}")

    print(f"\nAudit trail: {audit.count()} records written to {audit.path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
