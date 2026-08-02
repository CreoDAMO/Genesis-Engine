"""
Simple strategy ensemble / portfolio layer.
Allocates simulated capital across hall-of-fame genomes and reports
portfolio-level metrics. Still fully simulated and VM-contained.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple
import numpy as np

from bytecode_vm import compile_ast, execute, MAX_FUEL, FEATURE_INDEX
from genetic_strategy_engine import StrategyGenome, _clip


def _feature_vector(market_data: Dict[str, np.ndarray], p: int, t: int, prev_sig: float, n_steps: int) -> List[float]:
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


def evaluate_portfolio(
    genomes: Sequence[StrategyGenome],
    market_data: Dict[str, np.ndarray],
    weights: Sequence[float] | None = None,
) -> Dict[str, float]:
    """
    Equal-weight (or supplied) portfolio of strategies.
    Returns portfolio Sharpe, mean return, max drawdown, and pairwise signal correlation.
    """
    if not genomes:
        return {"sharpe": 0.0, "mean_return": 0.0, "max_dd": 0.0, "avg_corr": 0.0}

    n = len(genomes)
    if weights is None:
        w = np.ones(n) / n
    else:
        w = np.asarray(weights, dtype=float)
        w = w / (w.sum() + 1e-12)

    compiled = []
    for g in genomes:
        try:
            cs = compile_ast(g.ast_tree, g.source)
            compiled.append(cs)
        except Exception:
            compiled.append(None)

    n_paths, n_steps = market_data["mid"].shape
    # Collect per-strategy path returns and also a portfolio equity curve
    strat_returns = np.zeros((n, n_paths))
    port_path_returns = np.zeros(n_paths)
    all_signals = [[] for _ in range(n)]

    for p in range(n_paths):
        prev_sigs = [0.0] * n
        path_pnl = np.zeros(n)
        for t in range(n_steps - 1):
            step_pnls = []
            for i, cs in enumerate(compiled):
                if cs is None:
                    step_pnls.append(0.0)
                    continue
                feats = _feature_vector(market_data, p, t, prev_sigs[i], n_steps)
                try:
                    raw = execute(cs, feats, max_fuel=MAX_FUEL)
                    sig = float(_clip(raw))
                except Exception:
                    sig = 0.0
                ret = float(market_data["mid"][p, t + 1] - market_data["mid"][p, t])
                cost = 0.0008 * abs(sig - prev_sigs[i])
                pnl = sig * ret - cost
                step_pnls.append(pnl)
                path_pnl[i] += pnl
                prev_sigs[i] = sig
                all_signals[i].append(sig)

            port_path_returns[p] += float(np.dot(w, step_pnls))

        strat_returns[:, p] = path_pnl

    # Portfolio metrics
    mean_r = float(np.mean(port_path_returns))
    std_r = float(np.std(port_path_returns) + 1e-9)
    sharpe = mean_r / std_r * np.sqrt(252)

    # Max drawdown on concatenated equity (simple)
    equity = np.cumprod(1.0 + port_path_returns)
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / (peak + 1e-12)
    max_dd = float(np.max(dd))

    # Average pairwise signal correlation
    corrs = []
    for i in range(n):
        for j in range(i + 1, n):
            if len(all_signals[i]) > 5 and len(all_signals[j]) > 5:
                c = np.corrcoef(all_signals[i], all_signals[j])[0, 1]
                if np.isfinite(c):
                    corrs.append(float(c))
    avg_corr = float(np.mean(corrs)) if corrs else 0.0

    return {
        "sharpe": sharpe,
        "mean_return": mean_r,
        "max_dd": max_dd,
        "avg_corr": avg_corr,
        "n_strategies": n,
    }
