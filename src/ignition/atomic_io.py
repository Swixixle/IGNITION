"""Atomic file writes to avoid torn JSON on crash."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def atomic_write_json(path: Path, obj: Any, *, indent: int = 2) -> None:
    text = json.dumps(obj, indent=indent, ensure_ascii=False) + ("\n" if indent else "")
    atomic_write_text(path, text)


def safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        return json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
