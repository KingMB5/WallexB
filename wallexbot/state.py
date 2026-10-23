"""
state.py — crash-safe JSON state (positions, trades, equity history).

The state file never contains credentials — brokers and config are redacted by
design; state.py additionally strips any key that looks secret before writing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .redact import is_secret_key


def load_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: str, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    def _strip(obj):
        if isinstance(obj, dict):
            return {k: "<redacted>" if is_secret_key(k) else _strip(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_strip(x) for x in obj]
        return obj

    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(_strip(state), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)  # atomic on POSIX
