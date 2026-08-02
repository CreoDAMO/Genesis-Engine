"""
Genesis Engine — Configuration Loader
Loads YAML config with environment variable substitution.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml


class Config:
    """Dot-accessible nested config."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data
        for k, v in data.items():
            if isinstance(v, dict):
                setattr(self, k, Config(v))
            else:
                setattr(self, k, v)

    def to_dict(self) -> Dict[str, Any]:
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


def _env_substitute(value: Any) -> Any:
    """Replace ${VAR} or ${VAR:-default} with environment values."""
    if isinstance(value, str):
        pattern = re.compile(r"\\$\{([^}]+)\}")

        def replacer(m):
            expr = m.group(1)
            if ":-" in expr:
                var, default = expr.split(":-", 1)
                return os.environ.get(var, default)
            return os.environ.get(expr, "")

        return pattern.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _env_substitute(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_env_substitute(v) for v in value]
    return value


def load_config(path: str | Path = "config/config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p.absolute()}")
    with open(p, "r") as f:
        raw = yaml.safe_load(f)
    resolved = _env_substitute(raw)
    return Config(resolved)
