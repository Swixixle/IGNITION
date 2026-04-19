"""Compute session status: drift, counts, last checkpoint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ignition import git_ops
from ignition.config import IgnitionConfig
from ignition.utils import scope_drift_outside, scope_in_out_counts, top_out_of_scope


@dataclass
class SessionStatusView:
    repo_root: Path
    repo_name: str
    branch: str
    task: str
    changed_files_count: int
    untracked_count: int
    in_scope_count: int
    out_scope_count: int
    scope_drift_preview: list[str]
    last_checkpoint: dict[str, Any] | None
    last_commit_line: str
    recent_commits_excerpt: str
    scope_drift_warning: str | None
    tests_hint: str | None
    worktree_note: str | None


def _count_untracked(repo_root: Path) -> int:
    return len(git_ops.untracked_files(repo_root))


def build_status_view(
    repo_root: Path,
    session: dict[str, Any],
    cfg: IgnitionConfig,
) -> SessionStatusView:
    branch = git_ops.get_current_branch(repo_root)
    changed = git_ops.changed_files(repo_root)
    untracked = _count_untracked(repo_root)
    checkpoints = session.get("checkpoints") or []
    last_cp = checkpoints[-1] if checkpoints else None
    head = git_ops.head_hash(repo_root)
    last_commit_line = head[:12]
    n = max(1, cfg.max_recent_commits)
    recent = git_ops.recent_commits(repo_root, n=n)

    scope = session.get("scope") or []
    inside, outside = scope_in_out_counts(repo_root, changed, scope)
    preview = top_out_of_scope(
        repo_root,
        changed,
        scope,
        cfg.scope_drift_preview_limit,
    )
    drift = scope_drift_outside(repo_root, changed, scope)
    warn: str | None = None
    if cfg.warn_on_scope_drift and scope and len(drift) >= cfg.max_files_before_warning:
        warn = (
            f"{len(drift)} changed path(s) appear outside declared scope "
            f"(threshold: {cfg.max_files_before_warning}). Review scope or broaden it."
        )
    elif cfg.warn_on_scope_drift and scope and drift:
        warn = f"{len(drift)} changed path(s) outside declared scope (informational)."

    tests_hint = None
    cmd = cfg.auto_status_test_command or cfg.auto_checkpoint_test_command
    if cmd:
        tests_hint = f"Configured test command: {cmd}"

    wt_note = None
    if session.get("is_worktree") or git_ops.is_linked_worktree(repo_root):
        wt_note = git_ops.worktree_label(repo_root)

    return SessionStatusView(
        repo_root=repo_root,
        repo_name=session.get("repo_name", repo_root.name),
        branch=branch,
        task=session.get("task", ""),
        changed_files_count=len(changed),
        untracked_count=untracked,
        in_scope_count=inside,
        out_scope_count=outside,
        scope_drift_preview=preview,
        last_checkpoint=last_cp,
        last_commit_line=last_commit_line,
        recent_commits_excerpt=recent,
        scope_drift_warning=warn,
        tests_hint=tests_hint,
        worktree_note=wt_note,
    )
