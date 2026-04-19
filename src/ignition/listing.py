"""List sessions for inspectability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ignition import session as session_mod
from ignition.utils import parse_iso_duration_minutes


def session_to_row(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    started = data.get("started_at", "")
    stopped = data.get("stopped_at") or data.get("ended_at")
    duration_min = parse_iso_duration_minutes(started, stopped) if stopped and started else None
    return {
        "session_id": data.get("session_id", path.stem),
        "task": data.get("task", ""),
        "repo_name": data.get("repo_name", ""),
        "repo_root": data.get("repo_root", ""),
        "branch": data.get("branch", ""),
        "started_at": started,
        "stopped_at": stopped,
        "status": data.get("status", "unknown"),
        "duration_minutes": round(duration_min, 2) if duration_min is not None else None,
        "worktree_path": data.get("worktree_path"),
        "is_worktree": data.get("is_worktree"),
    }


def list_sessions(
    repo_root: Path,
    session_rel: str | None,
    *,
    limit: int = 20,
    all_repos: bool = False,
) -> list[dict[str, Any]]:
    paths = session_mod.iter_session_json_paths(repo_root, session_rel)
    current_root = str(repo_root.resolve())
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        data = session_mod.load_session_soft(path)
        if data is None:
            continue
        if not all_repos and data.get("repo_root") and data["repo_root"] != current_root:
            continue
        loaded.append((path, data))
    loaded.sort(key=lambda x: x[1].get("started_at", ""), reverse=True)
    return [session_to_row(p, d) for p, d in loaded[:limit]]
