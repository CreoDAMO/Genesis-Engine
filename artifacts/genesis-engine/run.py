#!/usr/bin/env python3
"""
Genesis Engine v5 — HTTP API entry point.

Sets up the Python path so the VM modules resolve correctly, then starts
the aiohttp API server.

Usage:
    cd artifacts/genesis-engine
    python run.py
"""

import os
import sys
from pathlib import Path

# Ensure the src/ package is importable and that src/vm/ is on sys.path
# so genetic_strategy_engine can find bytecode_vm and audit_trail via bare imports.
ROOT = Path(__file__).parent
SRC = ROOT / "src"
VM = SRC / "vm"

for p in (str(ROOT), str(SRC), str(VM)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Now import and start the server
from src.api_server import create_app  # noqa: E402
from aiohttp import web  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[Genesis Engine] Starting API server on port {port}")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)
