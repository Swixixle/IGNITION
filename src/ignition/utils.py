"""Small helpers: slugs, timestamps, scope matching."""

from __future__ import annotations

import fnmatch
import re
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str, max_len: int = 48) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    if not s:
        s = "session"
    return s[:max_len].rstrip("-")


def file_matches_scope(repo_root: Path, rel_path: str, scope: list[str]) -> bool:
    """Return True if rel_path (posix, relative to repo) matches any scope entry."""
    if not scope:
        return True
    rel = rel_path.replace("\\", "/").lstrip("./")
    for pattern in scope:
        p = pattern.replace("\\", "/").rstrip("/")
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, f"{p}/**"):
            return True
        if rel == p or rel.startswith(p + "/"):
            return True
        try:
            full = (repo_root / rel).resolve()
            candidate = (repo_root / p).resolve()
            if full == candidate or str(full).startswith(str(candidate) + "/"):
                return True
        except (OSError, ValueError):
            continue
    return False


def scope_drift_outside(
    repo_root: Path,
    changed_files: list[str],
    scope: list[str],
) -> list[str]:
    if not scope:
        return []
    return [f for f in changed_files if not file_matches_scope(repo_root, f, scope)]


def scope_in_out_counts(
    repo_root: Path,
    changed_files: list[str],
    scope: list[str],
) -> tuple[int, int]:
    if not scope:
        return len(changed_files), 0
    inside = sum(1 for f in changed_files if file_matches_scope(repo_root, f, scope))
    outside = len(changed_files) - inside
    return inside, outside


def top_out_of_scope(
    repo_root: Path,
    changed_files: list[str],
    scope: list[str],
    limit: int,
) -> list[str]:
    out = scope_drift_outside(repo_root, changed_files, scope)
    return out[:limit]


def parse_iso_duration_minutes(started_at: str, ended_at: str | None) -> float | None:
    """Return duration in minutes, or None if parsing fails."""
    if not ended_at or not started_at:
        return None
    try:
        s = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        e = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        return (e - s).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None


def truncate(s: str, max_chars: int = 8000) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n... [truncated]"
