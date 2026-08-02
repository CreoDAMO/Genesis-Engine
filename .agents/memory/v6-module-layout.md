---
name: v6 Module Layout
description: Where the six new v6 modules live and what each one does
---

## Layout

```
artifacts/genesis-engine/
├── omega_engine.py                        ← Orchestrator (CLI entry: python omega_engine.py)
└── src/
    ├── patches/
    │   ├── vm_hardening_patch.py          ← SafeMath, FitnessGate, AuditSanitizer
    │   └── gp_selection_fixes.py          ← LexicographicSelector, DiversityPreserver, SharpeFirstElitism
    ├── reality_surface/
    │   └── claim_normalizer.py            ← RealitySurface: PM + Deribit + funding → consensus prob
    ├── gravity/
    │   └── lp_dominance.py                ← GravityMarketMaker: inventory-skewed CLOB quoting
    └── sandbox/
        └── wasm_compiler.py               ← WASMStrategyCompiler (wasmtime or SafePythonVM fallback)
```

## Integration status
- `bytecode_vm.py` and `genetic_strategy_engine.py` — patched in place
- `omega_engine.py` — standalone orchestrator; has stubs for pm_client, deribit_client, gp_engine
- `run.py` — unchanged; still the main entry point for the aiohttp API

## Stubs waiting for wiring (in omega_engine.py)
1. `self.pm_client` → `src/api/polymarket_client.py`
2. `self.deribit_client` → `src/api/deribit_client.py`  
3. `self.gp_engine` → `src/vm/genetic_strategy_engine.py`
