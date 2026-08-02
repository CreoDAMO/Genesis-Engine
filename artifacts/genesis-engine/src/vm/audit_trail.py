"""
Immutable audit trail for genome evaluations.
Append-only JSONL. Each record is self-describing and hash-chained lightly.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional


class AuditTrail:
    def __init__(self, path: str = "audit_log.jsonl"):
        self.path = Path(path)
        self._last_hash = "genesis"
        # ensure file exists
        if not self.path.exists():
            self.path.write_text("")

    def _record_hash(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256((self._last_hash + raw).encode()).hexdigest()[:16]

    def log(
        self,
        event: str,
        genome_id: str,
        source: str,
        bytecode_hash: str,
        n_ops: int,
        fitness: float,
        fuel_limit: int,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload = {
            "ts": time.time(),
            "event": event,
            "genome_id": genome_id,
            "source": source[:200],
            "bytecode_hash": bytecode_hash,
            "n_ops": n_ops,
            "fitness": round(float(fitness), 6),
            "fuel_limit": fuel_limit,
            "prev_hash": self._last_hash,
        }
        if extra:
            payload["extra"] = extra

        h = self._record_hash(payload)
        payload["hash"] = h
        self._last_hash = h

        with self.path.open("a") as f:
            f.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return h

    def count(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for _ in self.path.open())

    def tail(self, n: int = 5) -> list:
        if not self.path.exists():
            return []
        lines = self.path.read_text().strip().splitlines()
        return [json.loads(l) for l in lines[-n:]]
