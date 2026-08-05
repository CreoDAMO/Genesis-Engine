"""
tests/test_wasm_vs_python.py

Regression test: WASM-compiled strategies must produce the same signal
as the SafePythonVM fallback on the same feature vector.

Covers:
  - Curated operator set (all GP operators except log/exp which fall back)
  - Evolved Hall-of-Fame-style strategies (complex nested trees)
  - Edge cases: div-by-zero, sign(0), nested if_else, clip boundaries
  - 10 synthetic Hall-of-Fame expressions sampled across operator space
"""

from __future__ import annotations

import math
import sys
import os

import pytest

# Make the sandbox and vm modules importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "sandbox"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wasm_compiler import WASMStrategyCompiler, HAS_WASMTIME


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def compiler():
    return WASMStrategyCompiler(fuel_limit=50_000)


# Standard 16-feature vector used across all tests
FEATS_NORMAL = [
    100.5,   # mid
    0.02,    # spread
    0.65,    # imbalance
    1_500.0, # volume
    58.3,    # rsi
    1.42,    # zscore
    0.35,    # momentum
    0.12,    # volatility
    0.47,    # time_frac
    0.10,    # prev_signal
    0.50,    # do_imbalance
    100.2,   # causal_mid
    0.30,    # shock
    0.08,    # confounder
    0.0,     # regime (calm)
    7.0,     # regime_age
]

# Feature vector with zeros / edge values to probe div-by-zero, sign(0), etc.
FEATS_EDGE = [
    0.0,   # mid = 0
    0.0,   # spread = 0  (div-by-zero probe)
    0.0,   # imbalance = 0  (sign(0) probe)
    0.0,   # volume = 0
    50.0,  # rsi
    0.0,   # zscore = 0  (sign(0) probe)
    0.0,   # momentum
    0.0,   # volatility = 0  (div-by-zero probe)
    0.0,   # time_frac
    0.0,   # prev_signal
    0.0,   # do_imbalance
    0.0,   # causal_mid
    0.0,   # shock
    0.0,   # confounder
    1.0,   # regime (stress)
    0.0,   # regime_age
]

# Feature vector with large values (clip / overflow probe)
FEATS_LARGE = [
    1e6, 100.0, 50.0, 1e8, 99.9, 20.0, 10.0, 5.0,
    0.99, 1.0, 50.0, 1e6, 100.0, 50.0, 1.0, 1000.0,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signals(compiler: WASMStrategyCompiler, expr: str, feats: list[float]):
    """Return (wasm_signal, python_signal). wasm_signal=None if no WASM."""
    compiler.clear_cache()
    compiled = compiler.compile(expr)

    py_sig = compiler._execute_python_fallback(compiled, feats)

    if compiled.wasm_bytes is not None:
        wasm_sig = compiler._execute_wasm(compiled, feats)
    else:
        wasm_sig = None

    return wasm_sig, py_sig


def _assert_match(wasm_sig, py_sig, expr: str, feats_label: str):
    """Assert WASM and Python signals are equal within float tolerance."""
    if wasm_sig is None:
        pytest.skip(f"No WASM (wasmtime not available or expr uses log/exp): {expr}")

    both_nan = math.isnan(wasm_sig) and math.isnan(py_sig)
    if both_nan:
        return  # NaN propagation matches

    assert not math.isnan(wasm_sig), f"WASM returned NaN but Python={py_sig:.6f} for [{expr}] ({feats_label})"
    assert not math.isnan(py_sig),   f"Python returned NaN but WASM={wasm_sig:.6f} for [{expr}] ({feats_label})"

    assert abs(wasm_sig - py_sig) < 1e-9, (
        f"WASM={wasm_sig:.9f} != Python={py_sig:.9f} for [{expr}] ({feats_label})"
    )


# ---------------------------------------------------------------------------
# Curated operator tests
# ---------------------------------------------------------------------------

CURATED_EXPRS = [
    # Binary arithmetic
    "add(zscore, imbalance)",
    "sub(rsi, 50.0)",
    "mul(zscore, imbalance)",
    "mul(momentum, 2.0)",
    # Safe division
    "div(momentum, volatility)",
    "div(zscore, spread)",      # spread=0 in FEATS_EDGE → NaN
    # Unary
    "neg(zscore)",
    "abs(momentum)",
    "sqrt(abs(zscore))",
    # sign — including sign(0.0) edge case
    "sign(zscore)",
    "sign(imbalance)",
    # Comparisons → 1.0 / 0.0
    "gt(rsi, 50.0)",
    "lt(spread, 0.01)",
    "ge(rsi, 50.0)",
    "le(volatility, 0.5)",
    "eq(regime, 1.0)",
    # max / min
    "max(zscore, momentum)",
    "min(zscore, momentum)",
    # clip
    "clip(zscore, -1.0, 1.0)",
    "clip(mul(rsi, 0.02), -1.0, 1.0)",
    # if_else
    "if_else(gt(rsi, 50.0), zscore, neg(zscore))",
    "if_else(regime, momentum, neg(momentum))",
    # Nested
    "add(mul(zscore, imbalance), sub(momentum, 0.5))",
    "mul(sign(zscore), abs(imbalance))",
    "div(sub(rsi, 50.0), max(volatility, 0.01))",
    "if_else(gt(abs(zscore), 1.0), sign(momentum), 0.0)",
    "clip(add(mul(zscore, 0.5), mul(imbalance, 0.5)), -1.0, 1.0)",
]


@pytest.mark.skipif(not HAS_WASMTIME, reason="wasmtime not installed")
@pytest.mark.parametrize("expr", CURATED_EXPRS)
def test_curated_normal_feats(compiler, expr):
    wasm, py = _signals(compiler, expr, FEATS_NORMAL)
    _assert_match(wasm, py, expr, "normal")


@pytest.mark.skipif(not HAS_WASMTIME, reason="wasmtime not installed")
@pytest.mark.parametrize("expr", CURATED_EXPRS)
def test_curated_edge_feats(compiler, expr):
    wasm, py = _signals(compiler, expr, FEATS_EDGE)
    _assert_match(wasm, py, expr, "edge")


@pytest.mark.skipif(not HAS_WASMTIME, reason="wasmtime not installed")
@pytest.mark.parametrize("expr", CURATED_EXPRS)
def test_curated_large_feats(compiler, expr):
    wasm, py = _signals(compiler, expr, FEATS_LARGE)
    _assert_match(wasm, py, expr, "large")


# ---------------------------------------------------------------------------
# log / exp fall back to Python — result is identical because same Python fn
# ---------------------------------------------------------------------------

FALLBACK_EXPRS = [
    "log(abs(zscore))",
    "exp(neg(zscore))",
    "add(log(abs(imbalance)), exp(neg(rsi)))",
    "mul(sign(zscore), log(abs(add(rsi, 0.1))))",
]


def test_log_exp_fallback_returns_finite(compiler):
    """log/exp expressions use SafePythonVM; result must be finite or NaN."""
    for expr in FALLBACK_EXPRS:
        compiler.clear_cache()
        compiled = compiler.compile(expr)
        assert compiled.wasm_bytes is None, f"Expected Python fallback for: {expr}"
        sig = compiler.execute(compiled, FEATS_NORMAL)
        assert math.isfinite(sig) or math.isnan(sig), f"Non-finite signal for {expr}: {sig}"


# ---------------------------------------------------------------------------
# Synthetic Hall-of-Fame — top-10 style evolved strategies
# ---------------------------------------------------------------------------
# These are complex, multi-level expression trees representative of what the
# GP engine produces.  Some contain log/exp (fall back to Python) and are
# tested only for Python consistency (not WASM vs Python).

HOF_STRATEGIES = [
    # 1. Momentum-imbalance interaction
    "mul(sign(momentum), abs(imbalance))",
    # 2. Zscore regime-gated
    "if_else(regime, mul(zscore, 0.5), mul(zscore, -0.5))",
    # 3. Mean-reversion signal clipped
    "clip(neg(zscore), -1.0, 1.0)",
    # 4. Spread-adjusted imbalance
    "div(imbalance, max(spread, 0.001))",
    # 5. Composite: RSI momentum cross
    "mul(sub(rsi, 50.0), sign(momentum))",
    # 6. Volatility-scaled zscore
    "div(zscore, max(volatility, 0.01))",
    # 7. Regime-conditioned momentum
    "if_else(gt(regime_age, 5.0), momentum, neg(momentum))",
    # 8. Causal imbalance comparison
    "mul(sub(imbalance, do_imbalance), sign(causal_mid))",
    # 9. Deep nested tree
    "if_else(gt(abs(zscore), 1.5), sign(mul(imbalance, momentum)), clip(zscore, -0.5, 0.5))",
    # 10. Shock-gated regime signal
    "if_else(gt(shock, 0.5), mul(neg(zscore), regime), mul(zscore, sub(1.0, regime)))",
]


@pytest.mark.skipif(not HAS_WASMTIME, reason="wasmtime not installed")
@pytest.mark.parametrize("expr", HOF_STRATEGIES)
def test_hof_wasm_matches_python_normal(compiler, expr):
    """Hall-of-Fame strategies: WASM output must equal Python output."""
    wasm, py = _signals(compiler, expr, FEATS_NORMAL)
    _assert_match(wasm, py, expr, "hof-normal")


@pytest.mark.skipif(not HAS_WASMTIME, reason="wasmtime not installed")
@pytest.mark.parametrize("expr", HOF_STRATEGIES)
def test_hof_wasm_matches_python_edge(compiler, expr):
    wasm, py = _signals(compiler, expr, FEATS_EDGE)
    _assert_match(wasm, py, expr, "hof-edge")


@pytest.mark.skipif(not HAS_WASMTIME, reason="wasmtime not installed")
def test_hof_wasm_uses_wasm_backend(compiler):
    """Strategies without log/exp must compile to real WASM bytes."""
    non_transcendental = [e for e in HOF_STRATEGIES if "log" not in e and "exp" not in e]
    for expr in non_transcendental:
        compiler.clear_cache()
        compiled = compiler.compile(expr)
        assert compiled.wasm_bytes is not None, (
            f"Expected WASM compilation but got Python fallback for: {expr}"
        )


# ---------------------------------------------------------------------------
# Compile-time properties
# ---------------------------------------------------------------------------

def test_compiler_caches_by_strategy_id(compiler):
    """Same strategy_id returns the same CompiledStrategy object."""
    compiler.clear_cache()
    c1 = compiler.compile("mul(zscore, imbalance)", strategy_id="s001")
    c2 = compiler.compile("mul(zscore, imbalance)", strategy_id="s001")
    assert c1 is c2


def test_compiler_auto_ids_by_content(compiler):
    """Auto-generated IDs are stable (same source → same id)."""
    compiler.clear_cache()
    c1 = compiler.compile("mul(zscore, imbalance)")
    compiler.clear_cache()
    c2 = compiler.compile("mul(zscore, imbalance)")
    assert c1.strategy_id == c2.strategy_id


def test_output_clamped_to_10(compiler):
    """All outputs must lie in [-10, 10]."""
    for expr in HOF_STRATEGIES + CURATED_EXPRS:
        compiler.clear_cache()
        compiled = compiler.compile(expr)
        for feats in [FEATS_NORMAL, FEATS_EDGE, FEATS_LARGE]:
            sig = compiler.execute(compiled, feats)
            if math.isfinite(sig):
                assert -10.0 <= sig <= 10.0, f"Out-of-range signal {sig} for {expr}"


def test_short_feature_vector_padded(compiler):
    """Feature vectors shorter than 16 must be zero-padded, not raise."""
    compiler.clear_cache()
    compiled = compiler.compile("mul(zscore, imbalance)")
    sig = compiler.execute(compiled, [0.0] * 8)   # only 8 features
    assert math.isfinite(sig) or math.isnan(sig)


def test_batch_execute(compiler):
    """batch_execute returns one result per compiled strategy."""
    exprs = ["mul(zscore, imbalance)", "sign(zscore)", "abs(momentum)"]
    compiled_list = [compiler.compile(e, strategy_id=f"b{i}") for i, e in enumerate(exprs)]
    results = compiler.batch_execute(compiled_list, FEATS_NORMAL)
    assert len(results) == len(exprs)
    for sig in results:
        assert math.isfinite(sig) or math.isnan(sig)
