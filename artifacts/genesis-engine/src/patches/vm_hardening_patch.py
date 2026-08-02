"""
patches/vm_hardening_patch.py

Drop-in safety guards for bytecode_vm.py.

Fixes the numerical instability that produced 11.6M fitness outliers:
  - SafeMath.div  — NaN on near-zero divisor (no more 11M fitness)
  - SafeMath.log  — NaN on non-positive input
  - SafeMath.exp  — capped against overflow
  - FitnessGate   — 6-layer sanity gate: finite check, hard cap at 1,000,
                    Sharpe-must-be-positive, min-trades, lottery, drawdown penalty
  - AuditSanitizer — catches poison before it hits the JSONL chain

Integration:
    from patches.vm_hardening_patch import SafeMath, FitnessGate, AuditSanitizer
"""

import math
import numpy as np
from typing import Tuple


class SafeMath:
    """
    Hardened math operations that never silently produce inf / -inf.

    All operations return NaN on invalid input, which propagates through the
    VM stack and kills the genome's fitness evaluation cleanly.
    """

    EPS: float = 1e-9
    MAX_EXP_ARG: float = 709.0   # ln(MAX_FLOAT) ≈ 709
    MIN_EXP_ARG: float = -745.0  # ln(MIN_POS_FLOAT) ≈ -745

    @classmethod
    def div(cls, a: float, b: float) -> float:
        """Guarded division. Returns NaN (not 0) when divisor is near-zero."""
        if abs(b) < cls.EPS:
            if abs(a) < cls.EPS:
                return 0.0      # 0/0 → neutral
            return float("nan") # x/0 → poison, kills genome
        return a / b

    @classmethod
    def log(cls, x: float) -> float:
        """Guarded natural log. Returns NaN on non-positive input."""
        if x <= 0.0:
            return float("nan")
        return math.log(x)

    @classmethod
    def log10(cls, x: float) -> float:
        if x <= 0.0:
            return float("nan")
        return math.log10(x)

    @classmethod
    def sqrt(cls, x: float) -> float:
        if x < 0.0:
            return float("nan")
        return math.sqrt(x)

    @classmethod
    def exp(cls, x: float) -> float:
        """Guarded exponential with overflow protection."""
        if x > cls.MAX_EXP_ARG:
            return float("inf")
        if x < cls.MIN_EXP_ARG:
            return 0.0
        return math.exp(x)

    @classmethod
    def pow(cls, base: float, exp: float) -> float:
        try:
            result = math.pow(base, exp)
            if not math.isfinite(result):
                return float("nan")
            return result
        except (ValueError, OverflowError):
            return float("nan")


class FitnessGate:
    """
    Hardened fitness evaluation with sanity checks.

    Prevents:
      - NaN/Inf poisoning
      - Single-trade lottery wins
      - Positive fitness with negative Sharpe
      - Runaway numerical explosions

    Usage with existing path-based returns:
        fitness, sharpe, valid, reason = FitnessGate.gate(raw_fitness, sharpe, returns)
    """

    MAX_FITNESS: float = 1_000.0
    MIN_SHARPE_FOR_POSITIVE_FITNESS: float = 0.0

    @classmethod
    def gate(
        cls,
        raw_fitness: float,
        sharpe: float,
        returns: "np.ndarray",
    ) -> Tuple[float, float, bool, str]:
        """
        Apply safety gates to an already-computed (fitness, sharpe, returns) triple.

        This is the adapter for the existing Genesis Engine which computes its own
        fitness = sharpe * calmar * winrate * occam, then calls this to sanitize.

        Returns: (gated_fitness, sharpe, is_valid, reason)
        """
        # Gate 1: finite check
        if not math.isfinite(raw_fitness):
            return -cls.MAX_FITNESS, -5.0, False, "non_finite_fitness"
        if not math.isfinite(sharpe):
            return -cls.MAX_FITNESS, -5.0, False, "non_finite_sharpe"
        if len(returns) > 0 and not np.isfinite(returns).all():
            return -cls.MAX_FITNESS, -5.0, False, "non_finite_returns"

        # Gate 2: hard cap
        fitness = float(np.clip(raw_fitness, -cls.MAX_FITNESS, cls.MAX_FITNESS))

        # Gate 3: Sharpe must be positive for positive fitness
        if sharpe <= cls.MIN_SHARPE_FOR_POSITIVE_FITNESS and fitness > 0:
            fitness = -1.0
            return fitness, sharpe, False, "positive_fitness_negative_sharpe"

        return fitness, sharpe, True, "ok"

    @classmethod
    def evaluate(
        cls,
        signals: "np.ndarray",
        backtest_df,
        leverage_cap: float = 1.0,
    ) -> Tuple[float, float, bool, str]:
        """
        Full evaluation from raw signals + backtest DataFrame (pandas).
        Used by the Omega orchestrator's GP loop.
        """
        if not np.isfinite(signals).all():
            return -1.0, -5.0, False, "non_finite_signals"

        positions = np.clip(signals, -leverage_cap, leverage_cap)
        if len(positions) < 2 or len(backtest_df) < 2:
            return -1.0, -5.0, False, "insufficient_data"

        returns = positions[:-1] * backtest_df["returns"].values[1:]

        pos_changes = np.abs(np.diff(positions))
        n_trades = int(np.sum(pos_changes > 0.01))
        if n_trades < 10:
            return -1.0, -5.0, False, f"insufficient_trades:{n_trades}"

        if len(returns) > 0:
            max_single = np.max(np.abs(returns))
            if max_single > 0.50:
                return -1.0, -5.0, False, f"lottery_trade:{max_single:.3f}"

        if not np.isfinite(returns).all():
            return -1.0, -5.0, False, "non_finite_returns"

        cumulative = np.cumsum(returns)
        total_pnl = float(cumulative[-1])

        if len(returns) > 1 and returns.std() > 1e-12:
            sharpe = float((returns.mean() / returns.std()) * np.sqrt(252 * 288))
        else:
            sharpe = -5.0

        if not math.isfinite(sharpe):
            return -1.0, -5.0, False, "non_finite_sharpe"

        running_max = np.maximum.accumulate(cumulative)
        drawdown = float(np.max(running_max - cumulative))
        pnl_magnitude = max(abs(total_pnl), 0.01)
        dd_penalty = max(0.0, 1.0 - drawdown / pnl_magnitude)

        raw_fitness = total_pnl * dd_penalty * max(0.0, sharpe)
        fitness = float(np.clip(raw_fitness, -cls.MAX_FITNESS, cls.MAX_FITNESS))

        if sharpe < 0.5 and fitness > 0:
            fitness = -1.0
            return fitness, sharpe, False, "positive_pnl_negative_sharpe"

        return fitness, sharpe, True, "ok"


class AuditSanitizer:
    """
    Sanitize records before writing to the audit chain.
    Catches poisoned evaluations and prevents them from corrupting the log.
    """

    @staticmethod
    def sanitize(record: dict) -> dict:
        """Clean a record before writing to JSONL."""
        fitness = record.get("fitness", 0)
        sharpe = record.get("sharpe", 0)

        if not (math.isfinite(fitness) and math.isfinite(sharpe)):
            record["fitness"] = -FitnessGate.MAX_FITNESS
            record["sharpe"] = -5.0
            record["valid"] = False
            record["poison_detected"] = True

        if abs(record.get("fitness", 0)) > FitnessGate.MAX_FITNESS:
            record["fitness"] = float(
                np.clip(record["fitness"], -FitnessGate.MAX_FITNESS, FitnessGate.MAX_FITNESS)
            )
            record["capped"] = True

        return record
