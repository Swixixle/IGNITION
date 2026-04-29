"""IGNITION MCP tool implementations.

Thin wrappers over the existing ``ignition.*`` modules. No parallel state,
no duplicated logic: any session/receipt created via MCP is bit-for-bit
identical on disk to one created via the CLI.

Every tool wraps its body in try/except and returns a structured error
dict on failure (mirrors KeySmith's pattern) so agent clients react
instead of hitting tool-error termination.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ignition import (
    bootstrap,
    carryforward,
    config,
    current_cmd,
    git_ops,
    resume as resume_mod,
    session as session_mod,
    status as status_mod,
)
from ignition.paths import config_path

log = logging.getLogger(__name__)

DEFAULT_PROJECT_ENV = "IGNITION_DEFAULT_PROJECT"


def _resolve_project(project_path: str | None) -> Path:
    """Resolve project_path with env-var fallback (mirrors KeySmith)."""
    if project_path is None or project_path.strip() == "":
        project_path = os.getenv(DEFAULT_PROJECT_ENV, ".")
    return Path(project_path).expanduser().resolve()


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"error": msg}
    out.update(extra)
    return out


def _load_active(repo_root: Path, cfg) -> tuple[Path | None, dict[str, Any] | None]:
    """Return (session_path, session_data) for the active session, or (None, None)."""
    raw = session_mod.read_active_pointer_raw(repo_root, cfg.session_dir)
    if not raw:
        return None, None
    p = Path(raw.get("session_file", ""))
    if not p.is_file():
        return None, None
    return p, session_mod.load_session(p)


# --------------- read-only tools ---------------


def ignition_current(project_path: str | None = None) -> dict[str, Any]:
    """Active-session snapshot, or {'active': False} if none."""
    try:
        repo_root = _resolve_project(project_path)
        if not repo_root.exists():
            return _err(f"Project path does not exist: {repo_root}")
        cfg = config.load_config(repo_root)
        _, session = _load_active(repo_root, cfg)
        if not session:
            return {"active": False, "repo_root": str(repo_root)}
        return current_cmd.build_current_payload(repo_root, session, cfg)
    except Exception as e:
        log.exception("ignition_current failed")
        return _err(str(e), project_path=str(project_path))


def ignition_next(
    project_path: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Carry-forward block from the last stopped session on this branch."""
    try:
        repo_root = _resolve_project(project_path)
        if not repo_root.exists():
            return _err(f"Project path does not exist: {repo_root}")
        cfg = config.load_config(repo_root)
        return carryforward.build_next_payload(repo_root, cfg, branch=branch)
    except Exception as e:
        log.exception("ignition_next failed")
        return _err(str(e), project_path=str(project_path))


def ignition_status(project_path: str | None = None) -> dict[str, Any]:
    """Full status view: scope, drift, last checkpoint, recent commits."""
    try:
        repo_root = _resolve_project(project_path)
        if not repo_root.exists():
            return _err(f"Project path does not exist: {repo_root}")
        cfg = config.load_config(repo_root)
        _, session = _load_active(repo_root, cfg)
        if not session:
            return {"active": False, "repo_root": str(repo_root)}
        view = status_mod.build_status_view(repo_root, session, cfg)
        return {
            "active": True,
            "repo_name": view.repo_name,
            "repo_root": str(view.repo_root),
            "branch": view.branch,
            "task": view.task,
            "scope": list(session.get("scope") or []),
            "changed_files_count": view.changed_files_count,
            "untracked_count": view.untracked_count,
            "in_scope_count": view.in_scope_count,
            "out_scope_count": view.out_scope_count,
            "scope_drift_preview": list(view.scope_drift_preview),
            "scope_drift_warning": view.scope_drift_warning,
            "last_checkpoint": view.last_checkpoint,
            "last_commit_line": view.last_commit_line,
            "recent_commits_excerpt": view.recent_commits_excerpt,
            "tests_hint": view.tests_hint,
            "worktree_note": view.worktree_note,
        }
    except Exception as e:
        log.exception("ignition_status failed")
        return _err(str(e), project_path=str(project_path))


# --------------- write tools ---------------


def ignition_init(
    project_path: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create ignition.toml and IGNITION data dirs.

    Refuses to overwrite an existing ignition.toml unless ``force=True``.
    Returns ``{"status": "already_initialized", "path": ...}`` in that case.
    The CLI's interactive prompts are NOT surfaced here — MCP callers get
    a deterministic outcome.
    """
    try:
        repo_root = _resolve_project(project_path)
        if not repo_root.exists():
            return _err(f"Project path does not exist: {repo_root}")
        cfg_path = config_path(repo_root)
        if cfg_path.is_file() and not force:
            return {
                "status": "already_initialized",
                "path": str(cfg_path),
                "hint": "Pass force=true to overwrite.",
            }
        if cfg_path.is_file() and force:
            cfg_path.unlink()
        cfg = config.load_config(repo_root)
        result = bootstrap.run_init(
            repo_root,
            cfg.session_dir,
            cfg.receipt_dir,
            cfg.templates_dir,
        )
        return {
            "status": "initialized" if result.created_config else "already_initialized",
            "path": str(result.config_path),
            "default_branch": result.default_branch,
            "suggested_test": result.suggested_test,
            "session_dir": str(result.session_dir),
            "receipt_dir": str(result.receipt_dir),
            "templates_dir": str(result.templates_dir),
            "repo_name": result.repo_name,
        }
    except Exception as e:
        log.exception("ignition_init failed")
        return _err(str(e), project_path=str(project_path))


def ignition_begin(
    task: str,
    project_path: str | None = None,
    scope: list[str] | None = None,
    definition_of_done: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Start a new session on the current branch.

    Guards (overridable with ``force=True``):
      * Refuses if an unfinished session already exists on this branch
        (suggests ``ignition_resume``).
      * Refuses if the active session pointer references a different clone
        of the same repo.
    """
    try:
        repo_root = _resolve_project(project_path)
        if not repo_root.exists():
            return _err(f"Project path does not exist: {repo_root}")
        if not task or not task.strip():
            return _err("task is required and cannot be empty")
        cfg = config.load_config(repo_root)

        if session_mod.pointer_repo_mismatch(repo_root, cfg.session_dir) and not force:
            return _err(
                "Active session pointer references a different clone of this repo.",
                code="pointer_repo_mismatch",
                hint="Pass force=true to override.",
            )

        branch = git_ops.get_current_branch_safe(repo_root)
        existing_path, existing = resume_mod.unfinished_on_branch(
            repo_root, cfg.session_dir, branch,
        )
        if existing and not force:
            return _err(
                f"Unfinished session already active on branch '{branch}'.",
                code="duplicate_session_same_branch",
                existing_session_id=existing.get("session_id"),
                existing_session_file=str(existing_path) if existing_path else None,
                hint="Call ignition_resume to continue, or pass force=true to override.",
            )

        scope_list = list(scope) if scope else list(cfg.preferred_scope)
        repo_name = repo_root.name
        initial_status = git_ops.status_porcelain(repo_root)
        initial_head = git_ops.head_hash(repo_root)
        worktree_path = str(repo_root.resolve())
        is_wt = git_ops.is_linked_worktree(repo_root)
        repo_default_branch = cfg.default_branch

        session_id, session_path = session_mod.create_session_record(
            repo_root,
            cfg.session_dir,
            cfg.receipt_dir,
            repo_name=repo_name,
            branch=branch,
            task=task.strip(),
            scope=scope_list,
            definition_of_done=definition_of_done,
            initial_git_status=initial_status,
            initial_head=initial_head,
            worktree_path=worktree_path,
            repo_default_branch=repo_default_branch,
            is_worktree=is_wt,
        )

        return {
            "status": "started",
            "session_id": session_id,
            "session_file": str(session_path),
            "branch": branch,
            "task": task.strip(),
            "scope": scope_list,
        }
    except Exception as e:
        log.exception("ignition_begin failed")
        return _err(str(e), project_path=str(project_path))


def ignition_resume(
    project_path: str | None = None,
    session_id: str | None = None,
    latest: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Rebind the active pointer to an unfinished session.

    With ``session_id``, resumes that specific session if it is unfinished.
    Otherwise picks the latest (or earliest with ``latest=False``) unfinished
    session for this repo.
    """
    try:
        repo_root = _resolve_project(project_path)
        if not repo_root.exists():
            return _err(f"Project path does not exist: {repo_root}")
        cfg = config.load_config(repo_root)

        if session_mod.pointer_repo_mismatch(repo_root, cfg.session_dir) and not force:
            return _err(
                "Active session pointer references a different clone of this repo.",
                code="pointer_repo_mismatch",
                hint="Pass force=true to override.",
            )

        path, data = resume_mod.find_resume_target(
            repo_root,
            cfg.session_dir,
            session_id=session_id,
            latest=latest,
        )
        if not path or not data:
            return _err(
                "No matching unfinished session found.",
                code="no_resume_target",
            )

        result = resume_mod.apply_resume(repo_root, cfg.session_dir, path, data)
        return {
            "status": "resumed",
            "session_id": result.data.get("session_id"),
            "session_file": str(result.session_path),
            "branch": result.data.get("branch"),
            "task": result.data.get("task"),
            "branch_warning": result.branch_warning,
            "head_warning": result.head_warning,
        }
    except Exception as e:
        log.exception("ignition_resume failed")
        return _err(str(e), project_path=str(project_path))


# --------------- registration helper ---------------

ALL_TOOLS = (
    ignition_current,
    ignition_next,
    ignition_status,
    ignition_init,
    ignition_begin,
    ignition_resume,
)
