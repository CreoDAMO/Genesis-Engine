#!/usr/bin/env python3
"""
Genesis Engine — Boundary Measurement Suite
===========================================
Quantitative stress tests of the bytecode containment layer.

Measures:
  1. Fuel exhaustion behavior
  2. Stack overflow behavior
  3. Compiler rejection of illegal ASTs
  4. Determinism
  5. Throughput (evals / sec)
  6. Relationship between expression depth/complexity and fuel used
  7. Clean failure modes under adversarial inputs
"""

from __future__ import annotations

import ast
import random
import time
import statistics
from typing import List, Tuple
import numpy as np

from bytecode_vm import (
    compile_ast,
    execute,
    disassemble,
    CompiledStrategy,
    CompileError,
    FuelExhausted,
    StackOverflow,
    StackUnderflow,
    VMError,
    MAX_FUEL,
    MAX_STACK,
    FEATURE_INDEX,
)
from genetic_strategy_engine import (
    GeneticStrategyEngine,
    generate_synthetic_markets,
    FEATURE_KEYS,
)


def make_deep_tree(depth: int) -> ast.AST:
    """Build a right-deep nested add tree (mainly stresses compiler depth / fuel)."""
    node: ast.AST = ast.Constant(value=1.0)
    for i in range(depth):
        node = ast.Call(
            func=ast.Name(id="add", ctx=ast.Load()),
            args=[node, ast.Constant(value=0.01)],
            keywords=[],
        )
    return node


def make_bushy_tree(depth: int) -> ast.AST:
    """Balanced binary tree of adds — maximizes simultaneous stack pressure."""
    def build(d: int) -> ast.AST:
        if d <= 0:
            return ast.Constant(value=0.1)
        return ast.Call(
            func=ast.Name(id="add", ctx=ast.Load()),
            args=[build(d - 1), build(d - 1)],
            keywords=[],
        )
    return build(depth)


def make_wide_tree(width: int) -> ast.AST:
    """Many sequential operations to burn fuel without deep stack."""
    node: ast.AST = ast.Name(id="mid", ctx=ast.Load())
    for i in range(width):
        node = ast.Call(
            func=ast.Name(id="add", ctx=ast.Load()),
            args=[node, ast.Constant(value=0.001 * (i % 5))],
            keywords=[],
        )
    return node


def random_features(seed: int = 0) -> List[float]:
    rng = np.random.default_rng(seed)
    return list(rng.uniform(-1.5, 1.5, size=10))


def section(title: str):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def test_fuel_exhaustion():
    section("1. FUEL EXHAUSTION")
    print(f"Quota: MAX_FUEL = {MAX_FUEL}")

    # Find the depth/width at which fuel is exhausted
    for width in [50, 100, 200, 400, 800, 1200, 1600, 2000]:
        tree = make_wide_tree(width)
        try:
            cs = compile_ast(tree, f"wide_{width}")
            fuel_needed = cs.n_ops  # lower bound
            print(f"  width={width:4d}  ops={cs.n_ops:4d}  ", end="")
            feats = random_features(1)
            # Give exactly the normal quota
            sig = execute(cs, feats, max_fuel=MAX_FUEL)
            print(f"OK  signal={sig:.4f}")
        except FuelExhausted:
            print("FUEL EXHAUSTED (expected for large width)")
            break
        except Exception as e:
            print(f"UNEXPECTED: {type(e).__name__}: {e}")
            break

    # Explicit kill test with artificially low fuel
    tree = make_wide_tree(30)
    cs = compile_ast(tree)
    try:
        execute(cs, random_features(), max_fuel=5)
        print("  FAIL: should have exhausted fuel with max_fuel=5")
    except FuelExhausted:
        print("  PASS: low fuel budget correctly kills strategy")


def test_stack_overflow():
    section("2. STACK OVERFLOW")
    print(f"Quota: MAX_STACK = {MAX_STACK}")
    print("Note: linear chains use almost no stack; bushy trees stress it.")

    # Bushy trees force higher peak stack
    for depth in range(1, 12):
        try:
            tree = make_bushy_tree(depth)
            cs = compile_ast(tree, f"bushy_{depth}")
            print(f"  bushy depth={depth:2d}  ops={cs.n_ops:5d}  ", end="")
            sig = execute(cs, random_features(2), max_stack=MAX_STACK, max_fuel=10000)
            print(f"OK  signal={sig:.4f}")
        except StackOverflow:
            print("STACK OVERFLOW (boundary hit)")
            break
        except FuelExhausted:
            print("FUEL EXHAUSTED before stack limit")
            break
        except CompileError as e:
            print(f"COMPILE REJECT: {e}")
            break
        except Exception as e:
            print(f"UNEXPECTED: {type(e).__name__}: {e}")
            break

    # Explicit low stack on a modest bushy tree
    try:
        tree = make_bushy_tree(4)
        cs = compile_ast(tree)
        execute(cs, random_features(), max_stack=2)
        print("  FAIL: should have overflowed with max_stack=2")
    except StackOverflow:
        print("  PASS: low stack budget correctly kills strategy")
    except Exception as e:
        print(f"  other: {type(e).__name__}: {e}")


def test_compiler_rejection():
    section("3. COMPILER REJECTION OF ILLEGAL ASTS")

    illegal_cases = [
        ("unknown feature", ast.Name(id="secret_key", ctx=ast.Load())),
        ("unknown function", ast.Call(
            func=ast.Name(id="os_system", ctx=ast.Load()),
            args=[ast.Constant(value="rm -rf /")],
            keywords=[],
        )),
        ("nested attribute (escape attempt)", ast.Attribute(
            value=ast.Name(id="mid", ctx=ast.Load()),
            attr="__class__",
            ctx=ast.Load(),
        )),
        ("subscript", ast.Subscript(
            value=ast.Name(id="mid", ctx=ast.Load()),
            slice=ast.Constant(value=0),
            ctx=ast.Load(),
        )),
    ]

    for name, node in illegal_cases:
        try:
            compile_ast(node, name)
            print(f"  FAIL: accepted illegal AST — {name}")
        except CompileError as e:
            print(f"  PASS: rejected — {name}  ({e})")
        except Exception as e:
            print(f"  PASS-ish: rejected with {type(e).__name__} — {name}")


def test_determinism():
    section("4. DETERMINISM")
    engine = GeneticStrategyEngine(population_size=8, max_depth=4, seed=99)
    engine.initialize()
    data = generate_synthetic_markets(n_paths=4, n_steps=16, seed=7)

    # Evaluate same genome three times
    g = engine.population[0]
    results = []
    for i in range(3):
        # reset fitness so evaluate always runs
        g.fitness = -np.inf
        fit = engine.evaluate(g, data)
        results.append(fit)

    if len(set(round(r, 10) for r in results)) == 1:
        print(f"  PASS: identical fitness across 3 runs → {results[0]:.6f}")
    else:
        print(f"  FAIL: non-deterministic results → {results}")


def test_throughput():
    section("5. THROUGHPUT")
    engine = GeneticStrategyEngine(population_size=40, max_depth=5, seed=42)
    engine.initialize()
    data = generate_synthetic_markets(n_paths=20, n_steps=48, seed=5)

    # Warm-up
    for g in engine.population[:5]:
        engine.evaluate(g, data)

    n = len(engine.population)
    t0 = time.perf_counter()
    for g in engine.population:
        g.fitness = -np.inf
        engine.evaluate(g, data)
    elapsed = time.perf_counter() - t0

    evals_per_sec = n / elapsed
    # each evaluate does n_paths * n_steps VM calls
    vm_calls = n * data["mid"].shape[0] * data["mid"].shape[1]
    vm_per_sec = vm_calls / elapsed

    print(f"  Population size     : {n}")
    print(f"  Market paths × steps : {data['mid'].shape}")
    print(f"  Wall time            : {elapsed:.3f} s")
    print(f"  Strategy evals/sec   : {evals_per_sec:.1f}")
    print(f"  VM calls/sec         : {vm_per_sec:,.0f}")


def test_depth_vs_fuel():
    section("6. DEPTH / COMPLEXITY vs FUEL USED")
    print(f"{'depth':>6}  {'ops':>5}  {'fuel_left':>10}  status")
    feats = random_features(3)
    for depth in range(1, 25, 2):
        tree = make_deep_tree(depth)
        try:
            cs = compile_ast(tree)
            # We don't have a fuel-remaining API, so we run with full quota
            # and just confirm it either succeeds or hits a clean limit.
            execute(cs, feats, max_fuel=MAX_FUEL)
            print(f"{depth:6d}  {cs.n_ops:5d}  {'OK':>10}")
        except FuelExhausted:
            print(f"{depth:6d}  {cs.n_ops:5d}  {'FUEL KILL':>10}")
            break
        except StackOverflow:
            print(f"{depth:6d}  {cs.n_ops:5d}  {'STACK KILL':>10}")
            break
        except Exception as e:
            print(f"{depth:6d}  ?????  {type(e).__name__}")
            break


def test_adversarial_random():
    section("7. ADVERSARIAL / RANDOM TREES (clean failure rate)")
    engine = GeneticStrategyEngine(population_size=100, max_depth=6, seed=123)
    engine.initialize()
    data = generate_synthetic_markets(n_paths=4, n_steps=12, seed=9)

    kills = {"fuel": 0, "stack": 0, "compile": 0, "other": 0, "ok": 0}
    for g in engine.population:
        try:
            from bytecode_vm import compile_ast as ca
            cs = ca(g.ast_tree, g.source)
            # force a tight fuel budget relative to size
            execute(cs, random_features(g.generation), max_fuel=max(10, cs.n_ops // 2))
            kills["ok"] += 1  # survived even tight budget
        except FuelExhausted:
            kills["fuel"] += 1
        except StackOverflow:
            kills["stack"] += 1
        except CompileError:
            kills["compile"] += 1
        except Exception:
            kills["other"] += 1

    total = sum(kills.values())
    print(f"  Random genomes tested : {total}")
    for k, v in kills.items():
        print(f"    {k:8s}: {v:3d}  ({100*v/total:.1f}%)")
    print("  Note: under a deliberately tight fuel budget most complex trees are killed cleanly.")


def main():
    print("Genesis Engine — Boundary Measurement Suite")
    print(f"Quotas under test: MAX_FUEL={MAX_FUEL}  MAX_STACK={MAX_STACK}")
    t0 = time.time()

    test_fuel_exhaustion()
    test_stack_overflow()
    test_compiler_rejection()
    test_determinism()
    test_throughput()
    test_depth_vs_fuel()
    test_adversarial_random()

    print()
    print("=" * 72)
    print(f"All measurements completed in {time.time()-t0:.2f}s")
    print("=" * 72)


if __name__ == "__main__":
    main()
