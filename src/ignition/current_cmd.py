"""`ignition current` — compact active-session snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ignition import git_ops
from ignition import status as status_mod
from ignition.config import IgnitionConfig
from ignition.utils import parse_iso_duration_minutes, utc_now_iso


def build_current_payload(repo_root: Path, session: dict[str, Any], cfg: IgnitionConfig) -> dict[str, Any]:
    view = status_mod.build_status_view(repo_root, session, cfg)
    now = utc_now_iso()
    dur = parse_iso_duration_minutes(session.get("started_at", ""), now)
    last_cp = view.last_checkpoint
    drift = view.scope_drift_warning
    return {
        "active": True,
        "repo_name": view.repo_name,
        "repo_root": str(view.repo_root),
        "session_id": session.get("session_id"),
        "task": view.task,
        "branch": view.branch,
        "started_at": session.get("started_at"),
        "duration_minutes_so_far": round(dur, 2) if dur is not None else None,
        "last_checkpoint_at": (last_cp or {}).get("at") if last_cp else None,
        "changed_files_count": view.changed_files_count,
        "scope_drift_warning": drift,
        "last_status_at": session.get("last_status_at"),
        "last_recommend_at": session.get("last_recommend_at"),
        "last_snapshot_at": session.get("last_snapshot_at"),
    }
