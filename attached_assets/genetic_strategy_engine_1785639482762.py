#!/usr/bin/env python3
"""
Genesis Engine v5.0-alpha — Autopoietic Strategy Core
Safe Genetic Program Synthesis of trading strategy ASTs.

Focus: substrate safety + evolutionary loop on synthetic binary markets.
No live trading, no external APIs, no unrestricted eval.
"""

from __future__ import annotations

import ast
import copy
import math
import random
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

from audit_trail import AuditTrail
from bytecode_vm import (
    compile_ast,
    execute,
    disassemble,
    CompiledStrategy,
    CompileError,
    FuelExhausted,
    StackOverflow,
    FEATURE_INDEX,
    MAX_FUEL,
)

# Feature namespace that strategies are allowed to read
FEATURE_KEYS = [
    "mid", "spread", "imbalance", "volume", "rsi", "zscore",
    "momentum", "volatility", "time_frac", "prev_signal",
    # causal / intervention terminals
    "do_imbalance", "causal_mid", "shock", "confounder",
    # regime
    "regime", "regime_age",
]

def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# Genome representation
# ---------------------------------------------------------------------------

@dataclass
class StrategyGenome:
    """A strategy is an AST expression + metadata."""
    ast_tree: ast.AST
    source: str
    fitness: float = -np.inf
    generation: int = 0
    parent_ids: List[str] = field(default_factory=list)
    complexity: int = 0
    id: str = ""

    def __post_init__(self):
        if not self.id:
            h = hashlib.sha1(self.source.encode()).hexdigest()[:10]
            self.id = f"g{self.generation}_{h}"

    def copy(self) -> "StrategyGenome":
        return StrategyGenome(
            ast_tree=copy.deepcopy(self.ast_tree),
            source=self.source,
            fitness=self.fitness,
            generation=self.generation,
            parent_ids=list(self.parent_ids),
            complexity=self.complexity,
            id=self.id,
        )


# ---------------------------------------------------------------------------
# Genetic operators
# ---------------------------------------------------------------------------

class GeneticStrategyEngine:
    """
    Evolves pure expression-tree strategies.
    Fitness is evaluated on synthetic binary-market trajectories.
    """

    # Allowed primitives (terminals + functions)
    # Arity only — actual execution is performed exclusively by the bytecode VM.
    TERMINALS = FEATURE_KEYS + ["const"]
    FUNCTIONS = {
        # unary
        "neg": 1,
        "abs": 1,
        "log": 1,
        "exp": 1,
        "clip": 1,
        "sign": 1,
        # binary
        "add": 2,
        "sub": 2,
        "mul": 2,
        "div": 2,
        "max": 2,
        "min": 2,
        "gt": 2,
        "lt": 2,
        # ternary
        "if_else": 3,
    }

    def __init__(
        self,
        population_size: int = 40,
        mutation_rate: float = 0.35,
        crossover_rate: float = 0.65,
        elitism: int = 4,
        max_depth: int = 6,
        tournament_size: int = 3,
        complexity_penalty: float = 0.015,
        seed: Optional[int] = None,
    ):
        self.pop_size = population_size
        self.mut_rate = mutation_rate
        self.cross_rate = crossover_rate
        self.elitism = elitism
        self.max_depth = max_depth
        self.tournament_size = tournament_size
        self.complexity_penalty = complexity_penalty
        self.rng = random.Random(seed)
        np.random.seed(seed)

        self.population: List[StrategyGenome] = []
        self.generation = 0
        self.hall_of_fame: List[StrategyGenome] = []
        self.history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Tree growth / mutation helpers
    # ------------------------------------------------------------------

    def _random_terminal(self) -> ast.AST:
        choice = self.rng.choice(self.TERMINALS)
        if choice == "const":
            # small constants useful for trading signals
            val = self.rng.choice([
                -1.0, -0.5, -0.2, 0.0, 0.2, 0.5, 1.0,
                self.rng.uniform(-1.5, 1.5)
            ])
            return ast.Constant(value=round(val, 4))
        return ast.Name(id=choice, ctx=ast.Load())

    def _random_tree(self, depth: int = 0, max_depth: Optional[int] = None) -> ast.AST:
        max_d = max_depth if max_depth is not None else self.max_depth
        # force terminal near depth limit
        if depth >= max_d or (depth > 1 and self.rng.random() < 0.35):
            return self._random_terminal()

        name = self.rng.choice(list(self.FUNCTIONS.keys()))
        arity = self.FUNCTIONS[name]

        args = [self._random_tree(depth + 1, max_d) for _ in range(arity)]
        return ast.Call(
            func=ast.Name(id=name, ctx=ast.Load()),
            args=args,
            keywords=[],
        )

    def _tree_complexity(self, node: ast.AST) -> int:
        """Simple node count as complexity measure."""
        count = 1
        for child in ast.iter_child_nodes(node):
            count += self._tree_complexity(child)
        return count

    def _tree_to_source(self, tree: ast.AST) -> str:
        try:
            return ast.unparse(tree)
        except Exception:
            return "<unparseable>"

    def _make_genome(self, tree: ast.AST, generation: int = 0, parents: Optional[List[str]] = None) -> StrategyGenome:
        source = self._tree_to_source(tree)
        complexity = self._tree_complexity(tree)
        return StrategyGenome(
            ast_tree=tree,
            source=source,
            generation=generation,
            parent_ids=parents or [],
            complexity=complexity,
        )

    def _random_genome(self) -> StrategyGenome:
        tree = self._random_tree()
        return self._make_genome(tree, generation=self.generation)

    # ------------------------------------------------------------------
    # Genetic operators
    # ------------------------------------------------------------------

    def _tournament_select(self) -> StrategyGenome:
        contestants = self.rng.sample(self.population, k=min(self.tournament_size, len(self.population)))
        return max(contestants, key=lambda g: g.fitness)

    def _crossover(self, p1: StrategyGenome, p2: StrategyGenome) -> StrategyGenome:
        """Subtree crossover."""
        t1 = copy.deepcopy(p1.ast_tree)
        t2 = copy.deepcopy(p2.ast_tree)

        # collect all nodes that can be replaced (prefer internal)
        def collect(node, nodes):
            nodes.append(node)
            for child in ast.iter_child_nodes(node):
                collect(child, nodes)

        nodes1: List[ast.AST] = []
        nodes2: List[ast.AST] = []
        collect(t1, nodes1)
        collect(t2, nodes2)

        if not nodes1 or not nodes2:
            return p1.copy()

        # pick random subtrees
        n1 = self.rng.choice(nodes1)
        n2 = self.rng.choice(nodes2)

        # replace n1 with n2 by walking the tree (simple approach: rebuild via source is fragile;
        # we do a shallow structural swap by replacing the chosen node reference where possible)
        # For robustness we re-grow from a random point or fall back to one parent.
        try:
            # Prefer: replace a random child of a Call
            def replace_subtree(root, target, replacement):
                if root is target:
                    return replacement
                for field, value in ast.iter_fields(root):
                    if isinstance(value, list):
                        for i, item in enumerate(value):
                            if isinstance(item, ast.AST):
                                value[i] = replace_subtree(item, target, replacement)
                    elif isinstance(value, ast.AST):
                        setattr(root, field, replace_subtree(value, target, replacement))
                return root

            new_tree = replace_subtree(t1, n1, n2)
            # depth check
            if self._tree_complexity(new_tree) > 80:
                return p1.copy()
            return self._make_genome(new_tree, generation=self.generation + 1, parents=[p1.id, p2.id])
        except Exception:
            return p1.copy()

    def _mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """Point mutation: replace a random subtree with a new random tree."""
        tree = copy.deepcopy(genome.ast_tree)

        nodes: List[ast.AST] = []
        def collect(n):
            nodes.append(n)
            for c in ast.iter_child_nodes(n):
                collect(c)
        collect(tree)

        if not nodes:
            return genome.copy()

        target = self.rng.choice(nodes)
        new_subtree = self._random_tree(depth=0, max_depth=max(2, self.max_depth - 2))

        def replace(root, target, replacement):
            if root is target:
                return replacement
            for field, value in ast.iter_fields(root):
                if isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, ast.AST):
                            value[i] = replace(item, target, replacement)
                elif isinstance(value, ast.AST):
                    setattr(root, field, replace(value, target, replacement))
            return root

        try:
            new_tree = replace(tree, target, new_subtree)
            if self._tree_complexity(new_tree) > 90:
                return genome.copy()
            return self._make_genome(new_tree, generation=self.generation + 1, parents=[genome.id])
        except Exception:
            return genome.copy()

    # ------------------------------------------------------------------
    # Safe evaluation
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Safe evaluation — bytecode VM only
    # ------------------------------------------------------------------

    def _compile_to_bytecode(self, genome: StrategyGenome) -> Optional[CompiledStrategy]:
        """Compile the genome AST into metered bytecode. Returns None on failure."""
        try:
            return compile_ast(genome.ast_tree, genome.source)
        except (CompileError, Exception):
            return None


    def evaluate(self, genome: StrategyGenome, market_data: Dict[str, np.ndarray],
                 audit: "AuditTrail | None" = None) -> float:
        """
        Evaluate strategy exclusively through the fuel-metered bytecode VM.
        Feature vector now includes causal + regime terminals.
        """
        cs = self._compile_to_bytecode(genome)
        if cs is None:
            genome.fitness = -100.0
            return genome.fitness

        bytecode_hash = hashlib.sha1(cs.code).hexdigest()[:12]
        n_paths = market_data["mid"].shape[0]
        n_steps = market_data["mid"].shape[1]
        returns = []
        signals = []

        try:
            for p in range(n_paths):
                path_ret = 0.0
                prev_sig = 0.0
                equity = 1.0
                peak = 1.0
                max_dd = 0.0

                for t in range(n_steps):
                    # Ordered feature vector matching FEATURE_INDEX (16 entries)
                    feats = [
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

                    try:
                        raw = execute(cs, feats, max_fuel=MAX_FUEL)
                        sig = float(_clip(raw))
                    except (FuelExhausted, StackOverflow, Exception):
                        sig = 0.0

                    if t < n_steps - 1:
                        next_mid = float(market_data["mid"][p, t + 1])
                        ret = next_mid - feats[0]
                        cost = 0.0008 * abs(sig - prev_sig)
                        step_pnl = sig * ret - cost
                        path_ret += step_pnl
                        equity *= (1.0 + step_pnl)
                        peak = max(peak, equity)
                        dd = (peak - equity) / peak if peak > 0 else 0.0
                        max_dd = max(max_dd, dd)

                    prev_sig = sig
                    signals.append(sig)

                returns.append(path_ret)

            rets = np.array(returns)
            mean_r = float(np.mean(rets))
            std_r = float(np.std(rets) + 1e-9)
            sharpe = mean_r / std_r * math.sqrt(252)
            win_rate = float(np.mean([1 if r > 0 else 0 for r in returns]))

            fitness = (
                0.45 * sharpe
                + 0.25 * (win_rate * 2 - 1)
                + 0.20 * mean_r * 50
                - self.complexity_penalty * genome.complexity
            )
            sig_std = float(np.std(signals)) if signals else 0.0
            if sig_std > 0.85:
                fitness -= 0.3

            genome.fitness = float(fitness)

            if audit is not None:
                audit.log(
                    event="evaluate",
                    genome_id=genome.id,
                    source=genome.source,
                    bytecode_hash=bytecode_hash,
                    n_ops=cs.n_ops,
                    fitness=genome.fitness,
                    fuel_limit=MAX_FUEL,
                    extra={"generation": genome.generation, "complexity": genome.complexity},
                )

            return genome.fitness
        except Exception:
            genome.fitness = -50.0
            return genome.fitness


    def initialize(self):
        self.population = [self._random_genome() for _ in range(self.pop_size)]
        self.generation = 0
        self.hall_of_fame = []
        self.history = []

    def evolve_one_generation(self, market_data: Dict[str, np.ndarray]):
        # evaluate
        for g in self.population:
            if g.fitness == -np.inf:
                self.evaluate(g, market_data)

        # sort
        self.population.sort(key=lambda g: g.fitness, reverse=True)

        # update hall of fame
        for g in self.population[:3]:
            if not any(h.id == g.id for h in self.hall_of_fame):
                self.hall_of_fame.append(g.copy())
        self.hall_of_fame.sort(key=lambda g: g.fitness, reverse=True)
        self.hall_of_fame = self.hall_of_fame[:10]

        best = self.population[0]
        avg = float(np.mean([g.fitness for g in self.population]))
        self.history.append({
            "gen": self.generation,
            "best": best.fitness,
            "avg": avg,
            "best_source": best.source,
            "complexity": best.complexity,
        })

        # produce next generation
        next_pop: List[StrategyGenome] = []

        # elitism
        for i in range(min(self.elitism, len(self.population))):
            elite = self.population[i].copy()
            elite.generation = self.generation + 1
            next_pop.append(elite)

        while len(next_pop) < self.pop_size:
            if self.rng.random() < self.cross_rate and len(self.population) >= 2:
                p1 = self._tournament_select()
                p2 = self._tournament_select()
                child = self._crossover(p1, p2)
            else:
                child = self._tournament_select().copy()

            if self.rng.random() < self.mut_rate:
                child = self._mutate(child)

            # reset fitness so it is re-evaluated
            child.fitness = -np.inf
            child.generation = self.generation + 1
            next_pop.append(child)

        self.population = next_pop[: self.pop_size]
        self.generation += 1

    def run(self, n_generations: int = 8, n_paths: int = 24, n_steps: int = 64, verbose: bool = True):
        market_data = generate_synthetic_markets(n_paths=n_paths, n_steps=n_steps, seed=42)
        self.initialize()

        # initial evaluation
        for g in self.population:
            self.evaluate(g, market_data)

        if verbose:
            print(f"{'Gen':>4}  {'Best':>8}  {'Avg':>8}  {'Cx':>4}  Strategy")
            print("-" * 72)

        for gen in range(n_generations):
            self.evolve_one_generation(market_data)
            if verbose:
                h = self.history[-1]
                src = h["best_source"]
                if len(src) > 48:
                    src = src[:45] + "..."
                print(f"{h['gen']:4d}  {h['best']:8.3f}  {h['avg']:8.3f}  {h['complexity']:4d}  {src}")

        return self.hall_of_fame


# ---------------------------------------------------------------------------
# Synthetic market data (binary prediction market style)
# ---------------------------------------------------------------------------


def generate_synthetic_markets(
    n_paths: int = 24,
    n_steps: int = 64,
    seed: int = 42,
    regime_shift: bool = True,
) -> Dict[str, np.ndarray]:
    """
    Synthetic binary prediction-market paths with:
      - optional mid-path regime shifts (calm ↔ stress)
      - a small causal DAG: shock → imbalance → mid, with a confounder
      - interventional feature do_imbalance and a simple causal_mid estimate
    All values remain pure floats for the bytecode VM.
    """
    rng = np.random.default_rng(seed)

    n_feat = 16  # must match FEATURE_INDEX length
    # We still return a dict keyed by name for readability; evaluation builds the vector.

    mid = np.zeros((n_paths, n_steps))
    spread = np.zeros((n_paths, n_steps))
    imbalance = np.zeros((n_paths, n_steps))
    volume = np.zeros((n_paths, n_steps))
    rsi = np.zeros((n_paths, n_steps))
    zscore = np.zeros((n_paths, n_steps))
    momentum = np.zeros((n_paths, n_steps))
    volatility = np.zeros((n_paths, n_steps))
    do_imbalance = np.zeros((n_paths, n_steps))
    causal_mid = np.zeros((n_paths, n_steps))
    shock = np.zeros((n_paths, n_steps))
    confounder = np.zeros((n_paths, n_steps))
    regime = np.zeros((n_paths, n_steps))
    regime_age = np.zeros((n_paths, n_steps))

    for p in range(n_paths):
        price = rng.uniform(0.25, 0.75)
        base_vol = rng.uniform(0.008, 0.022)
        conf = rng.normal(0, 0.3)          # path-level confounder
        current_regime = 0                 # 0 calm, 1 stress
        steps_in_regime = 0
        shift_point = n_steps // 2 + rng.integers(-8, 9) if regime_shift else n_steps + 1

        for t in range(n_steps):
            # Regime switch
            if regime_shift and t == shift_point:
                current_regime = 1 - current_regime
                steps_in_regime = 0
            steps_in_regime += 1

            # Regime parameters
            if current_regime == 0:  # calm
                vol = base_vol
                shock_prob = 0.03
                mean_reversion = 0.12
            else:  # stress
                vol = base_vol * 2.4
                shock_prob = 0.11
                mean_reversion = 0.04

            # Exogenous shock
            sk = 0.0
            if rng.random() < shock_prob:
                sk = float(rng.normal(0, 0.08 if current_regime == 0 else 0.14))
            shock[p, t] = sk

            # Causal structure (simplified):
            #   confounder C affects both imbalance and mid
            #   shock S → imbalance
            #   imbalance → mid
            # Observational imbalance
            imb = float(np.clip(
                0.55 * sk + 0.35 * conf + rng.normal(0, 0.25),
                -1.0, 1.0
            ))
            imbalance[p, t] = imb

            # Intervention: do(imbalance) = forced value (independent of shock/confounder)
            # We expose a synthetic intervention level the strategy can "read"
            do_imb = float(np.clip(rng.normal(0, 0.4), -1.0, 1.0))
            do_imbalance[p, t] = do_imb

            # Simple causal effect estimate: expected mid move under intervention
            # (in a real system this would come from the do-calculus engine)
            causal_effect = 0.22 * do_imb   # known structural coefficient in the sim
            causal_mid[p, t] = causal_effect

            # Price dynamics
            price += rng.normal(0, vol) - mean_reversion * (price - 0.5) * 0.03
            price += 0.18 * imb + 0.10 * conf + sk * 0.5
            price = float(np.clip(price, 0.05, 0.95))
            mid[p, t] = price

            spread[p, t] = rng.uniform(0.004, 0.025) * (1 + 1.8 * abs(price - 0.5)) * (1.4 if current_regime else 1.0)
            volume[p, t] = float(rng.lognormal(3.5, 0.55 + 0.3 * current_regime))
            confounder[p, t] = conf
            regime[p, t] = float(current_regime)
            regime_age[p, t] = steps_in_regime / max(n_steps, 1)

        # derived series
        returns = np.diff(mid[p], prepend=mid[p, 0])
        for t in range(n_steps):
            window = returns[max(0, t - 14) : t + 1]
            if len(window) > 2:
                up = np.sum(window[window > 0])
                down = -np.sum(window[window < 0])
                rs = up / (down + 1e-9)
                rsi[p, t] = 100 - (100 / (1 + rs))
            else:
                rsi[p, t] = 50.0
            w = mid[p, max(0, t - 20) : t + 1]
            zscore[p, t] = (mid[p, t] - np.mean(w)) / (np.std(w) + 1e-9)
            momentum[p, t] = mid[p, t] - mid[p, max(0, t - 5)]
            volatility[p, t] = float(np.std(returns[max(0, t - 10) : t + 1]) + 1e-6)

        rsi[p] = (rsi[p] - 50.0) / 50.0
        zscore[p] = np.clip(zscore[p], -3, 3) / 3.0
        momentum[p] = np.clip(momentum[p], -0.15, 0.15) / 0.15
        volume[p] = (volume[p] - np.mean(volume[p])) / (np.std(volume[p]) + 1e-9)

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




def main():
    print("=" * 72)
    print("Genesis Engine v5.0-alpha — Autopoietic Strategy Core")
    print("Causal terminals + regime shifts + ensemble + audit trail")
    print("=" * 72)
    print()

    from audit_trail import AuditTrail
    from portfolio import evaluate_portfolio

    audit = AuditTrail("audit_log.jsonl")
    # clear previous run for a clean demo
    open("audit_log.jsonl", "w").close()
    audit = AuditTrail("audit_log.jsonl")

    engine = GeneticStrategyEngine(
        population_size=32,
        mutation_rate=0.40,
        crossover_rate=0.60,
        elitism=4,
        max_depth=5,
        complexity_penalty=0.018,
        seed=7,
    )

    t0 = time.time()
    # Regime-shifting markets
    market_data = generate_synthetic_markets(n_paths=16, n_steps=48, seed=42, regime_shift=True)
    engine.initialize()

    # initial evaluation with audit
    for g in engine.population:
        engine.evaluate(g, market_data, audit=audit)

    print(f"{'Gen':>4}  {'Best':>8}  {'Avg':>8}  {'Cx':>4}  Strategy")
    print("-" * 72)

    for gen in range(8):
        engine.evolve_one_generation(market_data)
        # re-evaluate new population with audit
        for g in engine.population:
            if g.fitness == -np.inf:
                engine.evaluate(g, market_data, audit=audit)
        h = engine.history[-1]
        src_str = h["best_source"]
        if len(src_str) > 48:
            src_str = src_str[:45] + "..."
        print(f"{h['gen']:4d}  {h['best']:8.3f}  {h['avg']:8.3f}  {h['complexity']:4d}  {src_str}")

    elapsed = time.time() - t0
    hof = engine.hall_of_fame

    print()
    print("=" * 72)
    print(f"Finished in {elapsed:.1f}s  |  Generations: {engine.generation}")
    print(f"Audit records written: {audit.count()}")
    print()
    print("Hall of Fame (top strategies):")
    print("-" * 72)
    for i, g in enumerate(hof[:5]):
        print(f"{i+1}. fitness={g.fitness:7.3f}  cx={g.complexity:3d}  id={g.id}")
        print(f"   {g.source[:90]}")
        print()

    # Portfolio layer
    print("Portfolio ensemble (top-5 equal weight):")
    print("-" * 72)
    metrics = evaluate_portfolio(hof[:5], market_data)
    print(f"  strategies : {metrics['n_strategies']}")
    print(f"  Sharpe     : {metrics['sharpe']:.3f}")
    print(f"  mean ret   : {metrics['mean_return']:.4f}")
    print(f"  max DD     : {metrics['max_dd']:.3f}")
    print(f"  avg corr   : {metrics['avg_corr']:.3f}")
    print()

    print("Safety / containment notes:")
    print("  • All strategy logic runs only inside the fuel-metered bytecode VM.")
    print("  • Feature vector now includes causal (do_imbalance, causal_mid, shock, confounder)")
    print("    and regime (regime, regime_age) terminals — still pure numbers.")
    print("  • Markets contain mid-path regime shifts; strategies must adapt.")
    print("  • Every evaluation is append-only logged (genome id, bytecode hash, fitness).")
    print("=" * 72)


if __name__ == "__main__":
    main()
