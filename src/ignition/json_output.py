"""Stable JSON metadata for CLI --json outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ignition import __version__
from ignition.schema import CURRENT_SESSION_SCHEMA_VERSION
from ignition.utils import utc_now_iso


def json_envelope(payload: dict[str, Any], *, repo_root: Path | None = None) -> dict[str, Any]:
    """Merge command payload with stable top-level metadata (metadata wins on key clashes)."""
    meta: dict[str, Any] = {
        "tool_version": __version__,
        "schema_version": CURRENT_SESSION_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
    }
    if repo_root is not None:
        meta["repo_root"] = str(repo_root.resolve())
    return {**payload, **meta}
