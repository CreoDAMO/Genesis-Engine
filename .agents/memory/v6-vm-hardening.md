---
name: v6 VM Hardening
description: NaN-propagating SafeMath + FitnessGate; where they're wired into the existing engine
---

## Rule
`safe_div`, `safe_log`, `safe_exp` in `bytecode_vm.py` now return NaN on invalid input instead of silently clamping. This poisons the strategy's fitness and kills bad genomes cleanly instead of letting them survive with artificial signals.

`FitnessGate.gate()` caps fitness at ±1000 and rejects genomes with positive fitness + non-positive Sharpe — called inside `genetic_strategy_engine.py evaluate()`.

**Why:** Audit found 303 outliers (14%) with fitness > 100k (max 11.6M). Root cause was `div(..., imbalance)` hitting near-zero + `log(negative)` → NaN/Inf poisoning that produced arbitrarily large fitness values, decoupling fitness from Sharpe (r=0.03).

**How to apply:** When adding new VM opcodes, always use SafeMath methods. Never use raw `a / b`, `math.log(x)`, or `math.exp(x)` in the VM execution path.

## Where it lives
- `artifacts/genesis-engine/src/patches/vm_hardening_patch.py` — SafeMath, FitnessGate, AuditSanitizer
- `artifacts/genesis-engine/src/vm/bytecode_vm.py` — patched safe_div/safe_log/safe_exp (look for "v6 hardening" comments)
- `artifacts/genesis-engine/src/vm/genetic_strategy_engine.py` — FitnessGate.gate() called after fitness computation; AuditSanitizer on audit records
