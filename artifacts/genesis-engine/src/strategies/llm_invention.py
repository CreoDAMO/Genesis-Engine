"""
Genesis Engine — LLM Strategy Invention Engine
Uses live LLM APIs (OpenAI/Anthropic) to invent novel strategy classes.
Inventions are compiled to AST, backtested in VM, and auto-deployed if fitness > threshold.
"""

from __future__ import annotations

import ast
import json
import textwrap
from typing import Any, Dict, List, Optional

import openai

from src.vm.bytecode_vm import compile_ast, execute, MAX_FUEL
from src.vm.genetic_strategy_engine import generate_synthetic_markets, _clip, _sharpe, _calmar, _winrate
from src.vm.audit_trail import AuditTrail


class LLMStrategyInvention:
    """
    Meta-strategy layer: prompts LLM to invent new strategy expression trees.

    Pipeline:
      1. Detect fitness stagnation in GP population
      2. Prompt LLM with market context + strategy DSL
      3. Parse generated Python/AST
      4. Compile to bytecode
      5. Backtest on synthetic + recent real data
      6. If fitness > 20% improvement over HOF average -> deploy
    """

    SYSTEM_PROMPT = textwrap.dedent("""
        You are the Strategy Invention Engine for an autonomous trading system.
        Invent a novel trading strategy as a Python expression using ONLY these primitives:

        Features: mid, spread, imbalance, volume, rsi, zscore, momentum, volatility,
                  time_frac, prev_signal, do_imbalance, causal_mid, shock, confounder,
                  regime, regime_age

        Functions: add, sub, mul, div, max, min, gt, lt, neg, abs, log, exp, clip, sign, if_else

        Rules:
          - Return ONLY a valid Python expression (one line)
          - Do NOT use loops, imports, or external variables
          - The expression must return a float signal in [-1, 1]
          - Be creative: combine causal features, regime switches, and non-linear transforms
          - Example: if_else(gt(imbalance, 0.5), mul(regime, sub(causal_mid, mid)), clip(zscore))

        Invent a completely new strategy for this market regime:
    """)

    def __init__(self, api_key: str, model: str = "gpt-4o", temperature: float = 0.2,
                 deployment_threshold: float = 0.20, audit: Optional[AuditTrail] = None):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.deployment_threshold = deployment_threshold
        self.audit = audit
        self._invention_history: List[Dict[str, Any]] = []

    async def invent(self, market_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        prompt = self._build_prompt(market_context)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                max_tokens=512,
            )
            raw = response.choices[0].message.content.strip()
            expr = self._extract_expression(raw)
            if not expr:
                return None

            tree = ast.parse(expr, mode='eval').body
            cs = compile_ast(tree, expr)
            fitness = self._backtest(tree)

            result = {
                "source": expr,
                "fitness": fitness,
                "bytecode_ops": cs.n_ops,
                "deployed": False,
            }

            baseline = market_context.get("avg_fitness", 1.0)
            if baseline > 0 and fitness > baseline * (1 + self.deployment_threshold):
                result["deployed"] = True
                if self.audit:
                    import hashlib, time
                    self.audit.log(
                        event="LLM_INVENTION_DEPLOY",
                        genome_id=f"llm_{int(time.time())}",
                        source=expr,
                        bytecode_hash=hashlib.sha256(cs.code).hexdigest()[:16],
                        n_ops=cs.n_ops,
                        fitness=fitness,
                        fuel_limit=MAX_FUEL,
                        extra={"improvement": fitness / baseline - 1.0},
                    )

            self._invention_history.append(result)
            return result

        except Exception as e:
            return {"error": str(e), "source": "", "fitness": -1e6}

    def _build_prompt(self, ctx: Dict[str, Any]) -> str:
        return textwrap.dedent(f"""
            Current market regime: {ctx.get('regime', 'unknown')}
            Best fitness in population: {ctx.get('best_fitness', 0):.4f}
            Average fitness: {ctx.get('avg_fitness', 0):.4f}
            Stagnation for {ctx.get('stagnation_generations', 0)} generations.
            Top strategy: {ctx.get('top_strategy_source', 'N/A')}

            Invent a strategy expression that exploits this regime.
        """)

    def _extract_expression(self, raw: str) -> str:
        lines = raw.splitlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith("```") and not line.startswith("#"):
                return line
        return ""

    def _backtest(self, tree: ast.AST, n_paths: int = 10, n_steps: int = 50) -> float:
        import numpy as np
        data = generate_synthetic_markets(n_paths=n_paths, n_steps=n_steps, seed=None)
        n_p, n_s = data["mid"].shape
        path_returns = []

        for p in range(n_p):
            prev_sig = 0.0
            pnl = 0.0
            for t in range(n_s - 1):
                feats = [
                    float(data["mid"][p, t]),
                    float(data["spread"][p, t]),
                    float(data["imbalance"][p, t]),
                    float(data["volume"][p, t]),
                    float(data["rsi"][p, t]),
                    float(data["zscore"][p, t]),
                    float(data["momentum"][p, t]),
                    float(data["volatility"][p, t]),
                    float(t / max(n_s - 1, 1)),
                    prev_sig,
                    float(data["do_imbalance"][p, t]),
                    float(data["causal_mid"][p, t]),
                    float(data["shock"][p, t]),
                    float(data["confounder"][p, t]),
                    float(data["regime"][p, t]),
                    float(data["regime_age"][p, t]),
                ]
                try:
                    raw_sig = execute(compile_ast(tree, "<invention>"), feats, max_fuel=MAX_FUEL)
                    sig = _clip(float(raw_sig))
                except Exception:
                    sig = 0.0
                ret = float(data["mid"][p, t + 1] - data["mid"][p, t])
                cost = 0.0008 * abs(sig - prev_sig)
                pnl += sig * ret - cost
                prev_sig = sig
            path_returns.append(pnl)

        returns = np.array(path_returns)
        if np.std(returns) < 1e-9:
            return -1e6
        return _sharpe(returns) * max(0, _calmar(returns)) * _winrate(returns)
