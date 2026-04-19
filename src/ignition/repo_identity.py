"""Stable-ish repo fingerprint without network (local Git only)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ignition import git_ops


def compute_repo_identity(repo_root: Path) -> dict[str, Any]:
    """Identify a repo clone for import/export matching; not cryptographic proof."""
    rr = str(repo_root.resolve())
    name = repo_root.name
    git_dir = ""
    git_dir_hash = ""
    try:
        gd = git_ops.git_dir_abs(repo_root)
        git_dir = str(gd)
        git_dir_hash = hashlib.sha256(git_dir.encode("utf-8")).hexdigest()[:16]
    except Exception:
        pass
    return {
        "repo_root": rr,
        "repo_name": name,
        "git_dir_hash": git_dir_hash,
        "git_dir": git_dir,
    }
