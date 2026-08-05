"""
sandbox/wasm_compiler.py

Compile GP strategies to WASM for deterministic, sandboxed execution.
Replaces the Python AST interpreter with a compiled, fuel-metered sandbox.

Why WASM:
  - Deterministic: same input → same output across all hosts (IEEE 754)
  - Sandboxed: no memory access outside allocated buffer, no syscalls
  - Fast: JIT-compiled by the runtime (~100× Python AST)
  - Fuel-metered: instruction-count cap prevents infinite loops

Dependencies (optional):
    pip install wasmtime

Falls back to SafePythonVM if wasmtime is not installed.
"""

from __future__ import annotations

import math
import hashlib
import logging
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger("wasm_sandbox")

# Graceful fallback if wasmtime not installed
try:
    import wasmtime
    HAS_WASMTIME = True
except ImportError:
    HAS_WASMTIME = False
    logger.warning(
        "wasmtime not installed — using SafePythonVM fallback. "
        "Install with: pip install wasmtime"
    )


# Feature name → parameter index mapping (matches FEATURE_INDEX in bytecode_vm.py)
FEATURE_NAMES = [
    "mid", "spread", "imbalance", "volume", "rsi",
    "zscore", "momentum", "volatility", "time_frac", "prev_signal",
    "do_imbalance", "causal_mid", "shock", "confounder",
    "regime", "regime_age",
]
TERMINAL_MAP = {name: idx for idx, name in enumerate(FEATURE_NAMES)}


# ---------------------------------------------------------------------------
# Safe Python Fallback
# ---------------------------------------------------------------------------

class SafePythonVM:
    """
    Pure-Python fallback mimicking WASM semantics.

    Guards:
    - Division by near-zero → NaN
    - Log of non-positive → NaN
    - Fuel counter: max 10k operations
    - All results finite-checked
    """

    EPS = 1e-9
    MAX_FUEL = 10_000

    def __init__(self):
        self._fuel = self.MAX_FUEL

    def _burn(self, n: int = 1):
        self._fuel -= n
        if self._fuel <= 0:
            raise RuntimeError("Fuel exhausted — strategy exceeded instruction limit")

    def safe_div(self, a: float, b: float) -> float:
        self._burn()
        return float("nan") if abs(b) < self.EPS else a / b

    def safe_log(self, x: float) -> float:
        self._burn()
        return float("nan") if x <= 0.0 else math.log(x)

    def safe_sqrt(self, x: float) -> float:
        self._burn()
        return float("nan") if x < 0.0 else math.sqrt(x)

    def safe_exp(self, x: float) -> float:
        self._burn()
        if x > 709:
            return float("inf")
        if x < -745:
            return 0.0
        return math.exp(x)

    def execute(self, ast_fn: Callable, features: List[float]) -> float:
        self._fuel = self.MAX_FUEL
        try:
            result = ast_fn(features, vm=self)
            if not math.isfinite(result):
                return float("nan")
            return float(np.clip(result, -10.0, 10.0))
        except Exception as e:
            logger.debug(f"SafePythonVM execution error: {e}")
            return float("nan")


# ---------------------------------------------------------------------------
# WASM Compiler
# ---------------------------------------------------------------------------

@dataclass
class CompiledStrategy:
    strategy_id: str
    source_ast: str
    wasm_bytes: Optional[bytes]
    python_fn: Optional[Callable]
    compile_time_ms: float
    fuel_limit: int


class WASMStrategyCompiler:
    """
    Compiles strategy ASTs to WASM bytecode (or SafePythonVM fallback).

    Usage:
        compiler = WASMStrategyCompiler()
        compiled = compiler.compile("sign(mul(zscore, imbalance))", "s_001")
        signal = compiler.execute(compiled, features=[0.5, -0.2, 1.0, ...])
    """

    DEFAULT_FUEL = 10_000

    def __init__(self, fuel_limit: int = DEFAULT_FUEL):
        self.fuel_limit = fuel_limit
        self._cache: Dict[str, CompiledStrategy] = {}
        self._python_vm = SafePythonVM()

        if HAS_WASMTIME:
            cfg = wasmtime.Config()
            cfg.consume_fuel = True
            self._engine = wasmtime.Engine(cfg)
            logger.info("WASM compiler initialized with wasmtime backend")
        else:
            self._engine = None
            logger.info("WASM compiler initialized with SafePythonVM fallback")

    def compile(self, ast_source: str, strategy_id: Optional[str] = None) -> CompiledStrategy:
        """
        Compile an AST string to a CompiledStrategy.

        The WAT template handles basic expressions by mapping terminals to
        local parameters and operators to WASM instructions.
        A full production build would implement a complete AST→WASM walker.
        """
        if strategy_id is None:
            strategy_id = hashlib.sha256(ast_source.encode()).hexdigest()[:12]

        if strategy_id in self._cache:
            return self._cache[strategy_id]

        import time as _time
        t0 = _time.time()

        wasm_bytes = None
        if HAS_WASMTIME:
            wat = self._ast_to_wat(ast_source)
            if wat is not None:
                try:
                    wasm_bytes = wasmtime.wat2wasm(wat)
                except Exception as e:
                    logger.warning(f"WASM compile failed for {strategy_id}: {e} — using fallback")

        python_fn = self._ast_to_python_fn(ast_source)

        compiled = CompiledStrategy(
            strategy_id=strategy_id,
            source_ast=ast_source,
            wasm_bytes=wasm_bytes,
            python_fn=python_fn,
            compile_time_ms=(_time.time() - t0) * 1000,
            fuel_limit=self.fuel_limit,
        )
        self._cache[strategy_id] = compiled
        return compiled

    def execute(self, compiled: CompiledStrategy, features: List[float]) -> float:
        """
        Execute a compiled strategy on a feature vector (16 f64 values).
        Returns a signal in [-10, 10]. NaN if execution fails or fuel exhausted.
        """
        features = list(features)[:16]
        while len(features) < 16:
            features.append(0.0)

        if compiled.wasm_bytes is not None and HAS_WASMTIME:
            return self._execute_wasm(compiled, features)
        return self._execute_python_fallback(compiled, features)

    def _execute_wasm(self, compiled: CompiledStrategy, features: List[float]) -> float:
        try:
            store = wasmtime.Store(self._engine)
            store.set_fuel(self.fuel_limit)
            module = wasmtime.Module(self._engine, compiled.wasm_bytes)
            instance = wasmtime.Instance(store, module, [])
            strategy_fn = instance.exports(store)["strategy"]
            result = strategy_fn(store, *features)
            if not math.isfinite(result):
                return float("nan")
            return float(np.clip(result, -10.0, 10.0))
        except Exception as e:
            logger.debug(f"WASM execution failed: {e}")
            return float("nan")

    def _execute_python_fallback(self, compiled: CompiledStrategy, features: List[float]) -> float:
        if compiled.python_fn is None:
            return float("nan")
        return self._python_vm.execute(compiled.python_fn, features)

    # ------------------------------------------------------------------
    # AST → WAT (full recursive walker)
    # ------------------------------------------------------------------

    def _ast_to_wat(self, ast_source: str) -> Optional[str]:
        """
        Full recursive AST-string → WAT converter.

        Supported operators:
          Binary : add, sub, mul, div (safe — NaN on ÷0), max, min
          Unary  : neg, abs, sqrt, sign
          Compare: gt, lt, ge, le, eq  (return f64 1.0 / 0.0)
          Control: if_else(cond, then, else)
          3-arg  : clip(x, lo, hi)
          Terminals: any of the 16 named features, numeric literals

        Returns None for expressions that contain log() or exp() —
        those transcendentals have no native WASM instruction; the caller
        falls back to SafePythonVM automatically.
        """
        import ast as _py_ast

        # WASM has no f64.log / f64.exp — fall back to Python for those
        src_lower = ast_source.lower()
        if "log(" in src_lower or "exp(" in src_lower:
            return None

        try:
            tree = _py_ast.parse(ast_source, mode="eval")
        except SyntaxError:
            return None

        # Temp-local counter — each safe_div / sign needs a scratch local
        _tmp_count = [0]

        def _alloc() -> str:
            idx = _tmp_count[0]
            _tmp_count[0] += 1
            return f"$t{idx}"

        def _emit(node: _py_ast.expr) -> List[str]:
            """Return flat list of WAT instructions that leave one f64 on the stack."""

            # ── Numeric literal ──────────────────────────────────────
            if isinstance(node, _py_ast.Constant):
                return [f"f64.const {float(node.value)}"]

            # ── Feature terminal ─────────────────────────────────────
            if isinstance(node, _py_ast.Name):
                idx = TERMINAL_MAP.get(node.id, 0)
                return [f"local.get $p{idx}"]

            # ── Unary minus ──────────────────────────────────────────
            if isinstance(node, _py_ast.UnaryOp) and isinstance(node.op, _py_ast.USub):
                return _emit(node.operand) + ["f64.neg"]

            # ── Function calls ───────────────────────────────────────
            if isinstance(node, _py_ast.Call):
                fn = (node.func.id if isinstance(node.func, _py_ast.Name) else "").lower()
                args = node.args

                # Simple binary arithmetic
                _binary = {
                    "add": "f64.add", "sub": "f64.sub", "mul": "f64.mul",
                    "max": "f64.max", "maximum": "f64.max",
                    "min": "f64.min", "minimum": "f64.min",
                }
                if fn in _binary and len(args) == 2:
                    return _emit(args[0]) + _emit(args[1]) + [_binary[fn]]

                # Simple unary
                if fn in ("neg", "negate") and len(args) == 1:
                    return _emit(args[0]) + ["f64.neg"]
                if fn == "abs" and len(args) == 1:
                    return _emit(args[0]) + ["f64.abs"]
                if fn == "sqrt" and len(args) == 1:
                    return _emit(args[0]) + ["f64.sqrt"]

                # Safe div — emit b first, tee to local, check |b| < eps
                if fn == "div" and len(args) == 2:
                    tmp = _alloc()
                    return (
                        _emit(args[1]) +
                        [f"local.tee {tmp}",
                         "f64.abs",
                         "f64.const 1e-9",
                         "f64.lt",
                         "if (result f64)",
                         "  f64.const nan",
                         "else"] +
                        ["  " + i for i in _emit(args[0])] +
                        [f"  local.get {tmp}",
                         "  f64.div",
                         "end"]
                    )

                # sign(x) → 1.0 if x > 0, -1.0 if x < 0, 0.0 if x == 0
                if fn == "sign" and len(args) == 1:
                    tmp = _alloc()
                    return (
                        _emit(args[0]) +
                        [f"local.tee {tmp}",
                         "f64.const 0.0",
                         "f64.gt",
                         "if (result f64)",
                         "  f64.const 1.0",
                         "else",
                         f"  local.get {tmp}",
                         "  f64.const 0.0",
                         "  f64.lt",
                         "  if (result f64)",
                         "    f64.const -1.0",
                         "  else",
                         "    f64.const 0.0",
                         "  end",
                         "end"]
                    )

                # Comparisons → f64 1.0 or 0.0
                _cmps = {"gt": "f64.gt", "lt": "f64.lt",
                         "ge": "f64.ge", "le": "f64.le", "eq": "f64.eq"}
                if fn in _cmps and len(args) == 2:
                    return (
                        _emit(args[0]) + _emit(args[1]) +
                        [_cmps[fn],
                         "if (result f64)",
                         "  f64.const 1.0",
                         "else",
                         "  f64.const 0.0",
                         "end"]
                    )

                # if_else(cond, then, else): cond is f64; non-zero → true branch
                if fn == "if_else" and len(args) == 3:
                    return (
                        _emit(args[0]) +
                        ["f64.const 0.0", "f64.ne",
                         "if (result f64)"] +
                        ["  " + i for i in _emit(args[1])] +
                        ["else"] +
                        ["  " + i for i in _emit(args[2])] +
                        ["end"]
                    )

                # clip(x, lo, hi) → max(lo, min(hi, x))  (clamping order matters)
                if fn == "clip" and len(args) == 3:
                    return (
                        _emit(args[0]) +
                        _emit(args[1]) +
                        ["f64.max"] +
                        _emit(args[2]) +
                        ["f64.min"]
                    )

                # Unknown call — evaluate first arg or push 0
                if args:
                    return _emit(args[0])
                return ["f64.const 0.0"]

            # Anything else (shouldn't occur in GP ASTs)
            return ["f64.const 0.0"]

        try:
            body = _emit(tree.body)
        except Exception as exc:
            logger.debug(f"WAT emit error for '{ast_source[:60]}': {exc}")
            return None

        n_tmps = _tmp_count[0]
        params      = " ".join(f"(param $p{i} f64)" for i in range(16))
        locals_decl = "\n    ".join(f"(local $t{i} f64)" for i in range(n_tmps))
        body_text   = "\n    ".join(body)

        # Function body: optional locals, expression, output clamp to [-10, 10]
        inner = f"{locals_decl}\n    " if locals_decl else ""
        inner += f"{body_text}\n    f64.const -10.0\n    f64.max\n    f64.const 10.0\n    f64.min"

        return (
            f"(module\n"
            f"  (func $strategy {params} (result f64)\n"
            f"    {inner}\n"
            f"  )\n"
            f'  (export "strategy" (func $strategy))\n'
            f")"
        )

    # ------------------------------------------------------------------
    # AST → Python closure (full recursive evaluator, no eval())
    # ------------------------------------------------------------------

    def _ast_to_python_fn(self, ast_source: str) -> Callable:
        """
        Convert AST string to a Python closure via full recursive AST evaluation.

        Walks the parsed Python AST node tree — no eval(), no string matching.
        All 16 feature terminals and all GP operator names are handled.
        """
        import ast as _py_ast

        try:
            tree = _py_ast.parse(ast_source, mode="eval")
            expr = tree.body
        except SyntaxError:
            return lambda features, vm: 0.0

        def _eval(node: _py_ast.expr, features: List[float], vm: SafePythonVM) -> float:
            vm._burn()

            if isinstance(node, _py_ast.Constant):
                return float(node.value)

            if isinstance(node, _py_ast.Name):
                idx = TERMINAL_MAP.get(node.id, 0)
                return float(features[idx]) if idx < len(features) else 0.0

            if isinstance(node, _py_ast.UnaryOp) and isinstance(node.op, _py_ast.USub):
                return -_eval(node.operand, features, vm)

            if isinstance(node, _py_ast.Call):
                fn = (node.func.id if isinstance(node.func, _py_ast.Name) else "").lower()
                args = node.args

                # Lazy evaluation for if_else — only evaluate the taken branch
                if fn == "if_else" and len(args) == 3:
                    cond = _eval(args[0], features, vm)
                    return _eval(args[1], features, vm) if cond != 0.0 else _eval(args[2], features, vm)

                # Eagerly evaluate all other args
                eargs = [_eval(a, features, vm) for a in args]

                _ops: dict = {
                    "add":      lambda a, b:      a + b,
                    "sub":      lambda a, b:      a - b,
                    "mul":      lambda a, b:      a * b,
                    "div":      lambda a, b:      vm.safe_div(a, b),
                    "neg":      lambda a:         -a,
                    "negate":   lambda a:         -a,
                    "abs":      lambda a:         abs(a),
                    "sqrt":     lambda a:         vm.safe_sqrt(a),
                    "log":      lambda a:         vm.safe_log(a),
                    "exp":      lambda a:         vm.safe_exp(a),
                    "sign":     lambda a:         1.0 if a > 0 else (-1.0 if a < 0 else 0.0),
                    "max":      lambda a, b:      max(a, b),
                    "maximum":  lambda a, b:      max(a, b),
                    "min":      lambda a, b:      min(a, b),
                    "minimum":  lambda a, b:      min(a, b),
                    "gt":       lambda a, b:      1.0 if a > b else 0.0,
                    "lt":       lambda a, b:      1.0 if a < b else 0.0,
                    "ge":       lambda a, b:      1.0 if a >= b else 0.0,
                    "le":       lambda a, b:      1.0 if a <= b else 0.0,
                    "eq":       lambda a, b:      1.0 if a == b else 0.0,
                    "clip":     lambda a, lo, hi: max(lo, min(hi, a)),
                    "pow":      lambda a, b:      (
                        math.pow(abs(a), min(abs(b), 4.0)) if abs(a) > 1e-9 else 0.0
                    ),
                }

                if fn in _ops:
                    return _ops[fn](*eargs)

            return 0.0

        # Capture the parsed node in the closure (parse once, evaluate many times)
        _expr = expr

        def strategy_fn(features: List[float], vm: SafePythonVM) -> float:
            vm._fuel = vm.MAX_FUEL
            try:
                result = _eval(_expr, features, vm)
                if not math.isfinite(result):
                    return float("nan")
                return float(np.clip(result, -10.0, 10.0))
            except Exception:
                return float("nan")

        return strategy_fn

    def batch_execute(
        self,
        compiled_list: List[CompiledStrategy],
        features: List[float],
    ) -> List[float]:
        """Execute multiple strategies on the same feature vector."""
        return [self.execute(c, features) for c in compiled_list]

    def clear_cache(self):
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)
