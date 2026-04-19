"""Session records: create, load, active pointer, update."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ignition.atomic_io import atomic_write_json, safe_read_json
from ignition.paths import active_session_path, ensure_data_dirs, session_dir
from ignition import repo_identity as repo_identity_mod
from ignition import schema as schema_mod
from ignition.utils import slugify, utc_now_iso

POINTER_SCHEMA_VERSION = 1


def new_session_id(task: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{slugify(task)}"


def session_file_path(repo_root: Path, session_rel: str | None, session_id: str) -> Path:
    return session_dir(repo_root, session_rel) / f"{session_id}.json"


def write_active_pointer(
    repo_root: Path,
    session_rel: str | None,
    session_file: Path,
    session_id: str,
) -> None:
    p = active_session_path(repo_root, session_rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    rid = repo_identity_mod.compute_repo_identity(repo_root)
    payload = {
        "pointer_schema_version": POINTER_SCHEMA_VERSION,
        "session_file": str(session_file.resolve()),
        "repo_root": str(repo_root.resolve()),
        "session_id": session_id,
        "repo_identity": rid,
    }
    atomic_write_json(p, payload)


def read_active_pointer_raw(repo_root: Path, session_rel: str | None) -> dict[str, Any] | None:
    p = active_session_path(repo_root, session_rel)
    if not p.is_file():
        return None
    data = safe_read_json(p)
    if data is None:
        return None
    return data


def read_active_session_file(repo_root: Path, session_rel: str | None) -> Path | None:
    raw = read_active_pointer_raw(repo_root, session_rel)
    if not raw:
        return None
    path = Path(raw.get("session_file", ""))
    if path.is_file():
        return path
    return None


def pointer_repo_mismatch(repo_root: Path, session_rel: str | None) -> bool:
    raw = read_active_pointer_raw(repo_root, session_rel)
    if not raw:
        return False
    stored = raw.get("repo_root")
    if not stored:
        return False
    return Path(stored).resolve() != repo_root.resolve()


def clear_active_pointer(repo_root: Path, session_rel: str | None) -> None:
    p = active_session_path(repo_root, session_rel)
    if p.is_file():
        p.unlink()


def load_session(path: Path) -> dict[str, Any]:
    data = safe_read_json(path)
    if data is None:
        raise ValueError(f"Missing or invalid session JSON: {path}")
    return schema_mod.migrate_session(data)


def load_session_soft(path: Path) -> dict[str, Any] | None:
    """Return None on empty/malformed JSON (for directory scans)."""
    data = safe_read_json(path)
    if data is None:
        return None
    try:
        return schema_mod.migrate_session(data)
    except Exception:
        return None


def save_session(path: Path, data: dict[str, Any]) -> None:
    out = schema_mod.migrate_session(dict(data))
    atomic_write_json(path, out)


def iter_session_json_paths(repo_root: Path, session_rel: str | None) -> list[Path]:
    sdir = session_dir(repo_root, session_rel)
    if not sdir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(sdir.glob("*.json"), key=lambda x: x.name, reverse=True):
        if p.name == "current_session.json":
            continue
        out.append(p)
    return out


def is_session_unfinished(data: dict[str, Any]) -> bool:
    if data.get("status") in ("stopped", "stale_closed"):
        return False
    if data.get("stopped_at") or data.get("ended_at"):
        return False
    return True


def create_session_record(
    repo_root: Path,
    cfg_session_dir: str | None,
    cfg_receipt_dir: str | None,
    *,
    repo_name: str,
    branch: str,
    task: str,
    scope: list[str],
    definition_of_done: str,
    initial_git_status: str,
    initial_head: str,
    worktree_path: str | None = None,
    repo_default_branch: str | None = None,
    is_worktree: bool = False,
    resumed_from_session_id: str | None = None,
) -> tuple[str, Path]:
    ensure_data_dirs(repo_root, cfg_session_dir, cfg_receipt_dir)
    rid = repo_identity_mod.compute_repo_identity(repo_root)
    session_id = new_session_id(task)
    path = session_file_path(repo_root, cfg_session_dir, session_id)
    n = 0
    while path.exists():
        n += 1
        session_id = f"{new_session_id(task)}-{n}"
        path = session_file_path(repo_root, cfg_session_dir, session_id)

    record: dict[str, Any] = {
        "schema_version": schema_mod.CURRENT_SESSION_SCHEMA_VERSION,
        "repo_identity": rid,
        "session_id": session_id,
        "repo_name": repo_name,
        "repo_root": str(repo_root.resolve()),
        "branch": branch,
        "task": task,
        "scope": scope,
        "definition_of_done": definition_of_done,
        "started_at": utc_now_iso(),
        "initial_git_status": initial_git_status,
        "initial_head": initial_head,
        "status": "active",
        "checkpoints": [],
        "receipt_json": None,
        "receipt_md": None,
        "worktree_path": worktree_path or str(repo_root.resolve()),
        "is_worktree": is_worktree,
        "repo_default_branch": repo_default_branch,
        "resumed_from_session_id": resumed_from_session_id,
        "last_checkpoint_at": None,
        "last_test_status": None,
        "stopped_at": None,
        "final_status": None,
        "suggested_next_action": None,
        "snapshots": [],
        "last_status_at": None,
        "last_recommend_at": None,
        "last_snapshot_at": None,
        "recommend_events": [],
        "carryforward_todos": [],
        "carryforward_risks": [],
        "carryforward_questions": [],
        "carryforward_followups": [],
        "carryforward_summary": None,
        "carryforward_inherited": None,
        "linkage": {},
    }
    save_session(path, record)
    write_active_pointer(repo_root, cfg_session_dir, path, session_id)
    return session_id, path


def append_checkpoint(session_path: Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    data = load_session(session_path)
    data.setdefault("checkpoints", []).append(checkpoint)
    data["last_checkpoint_at"] = checkpoint.get("at")
    tr = checkpoint.get("test_result")
    if tr and isinstance(tr, dict) and not tr.get("skipped"):
        code = tr.get("exit_code")
        if code is None:
            data["last_test_status"] = "unknown"
        elif code == 0:
            data["last_test_status"] = "passed"
        else:
            data["last_test_status"] = "failed"
    save_session(session_path, data)
    return data


def mark_stopped(session_path: Path, extra: dict[str, Any]) -> dict[str, Any]:
    data = load_session(session_path)
    data["status"] = "stopped"
    data.update(extra)
    if "stopped_at" not in data and data.get("ended_at"):
        data["stopped_at"] = data["ended_at"]
    save_session(session_path, data)
    return data


def merge_session_update(session_path: Path, fields: dict[str, Any]) -> dict[str, Any]:
    data = load_session(session_path)
    data.update(fields)
    save_session(session_path, data)
    return data


def append_snapshot(session_path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    data = load_session(session_path)
    data.setdefault("snapshots", []).append(snapshot)
    save_session(session_path, data)
    return data
