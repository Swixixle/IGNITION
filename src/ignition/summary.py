"""Gather session-end facts, classify work state (v2), parking hints."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ignition import git_ops
from ignition.tests import TestRunResult
from ignition.utils import scope_drift_outside


@dataclass
class StopSummary:
    files_changed: list[str]
    diff_stat_session: str
    commits_during_session: list[str]
    commits_detailed: list[dict[str, str]]
    test_result: dict[str, Any] | None
    final_status: str
    scope_drift_warning: bool
    suggested_next_action: str
    cleanup_suggestions: list[str]
    parking_recommendations: dict[str, str] = field(default_factory=dict)
    file_stats: dict[str, Any] = field(default_factory=dict)


def test_result_to_dict(tr: TestRunResult | None) -> dict[str, Any] | None:
    if tr is None:
        return None
    return {
        "command": tr.command,
        "exit_code": tr.exit_code,
        "stdout_summary": tr.stdout_summary,
        "stderr_summary": tr.stderr_summary,
        "skipped": tr.skipped,
        "reason": tr.reason,
    }


def tests_failed(tr: TestRunResult | None) -> bool:
    return bool(
        tr
        and not tr.skipped
        and tr.exit_code is not None
        and tr.exit_code != 0
    )


def had_recovery_checkpoint(checkpoints: list[dict[str, Any]]) -> bool:
    for cp in checkpoints:
        if cp.get("wip_commit_hash") or cp.get("stash_message"):
            return True
    return False


def classify_work_state_v2(
    _repo_root: Path,
    _initial_head: str,
    *,
    working_tree_clean: bool,
    test_result: TestRunResult | None,
    checkpoints: list[dict[str, Any]],
    commits_since_start: list[str],
    _scope_drift: bool = False,
) -> tuple[str, str, list[str]]:
    """
    Return (primary_status, suggested_next_action, cleanup_suggestions).
    _scope_drift reserved for future coupling with classification rules.
    """
    cleanup: list[str] = []
    if tests_failed(test_result):
        return (
            "blocked_by_failing_tests",
            "Fix failing tests or adjust scope; rerun your test command until it passes.",
            [],
        )

    if not working_tree_clean:
        cleanup.extend(["git status", "git diff"])
        if had_recovery_checkpoint(checkpoints) or bool(commits_since_start):
            status = "dirty_checkpointed"
            msg = (
                "You have uncommitted changes but earlier checkpoints or commits exist; "
                "commit or stash to avoid losing context."
            )
        else:
            status = "dirty_uncommitted"
            msg = "Review diffs, then commit, stash, or discard as appropriate."
        cleanup.append('git stash push -u -m "wip: ignition session"')
        return (status, msg, cleanup)

    had_cp = bool(checkpoints) or bool(commits_since_start)
    if had_cp:
        msg = "Working tree clean; work is recorded on the branch — continue with PR/merge or a new session."
        cleanup.extend(
            [
                "git log --oneline @{u}..HEAD  # if upstream set",
                "# Optional (manual): git reset --soft main",
            ]
        )
        primary = "clean_in_progress"
    else:
        msg = "Working tree matches session start snapshot; nothing to merge from this session yet."
        primary = "clean_complete"

    return (primary, msg, cleanup)


def build_parking_recommendations(
    *,
    primary_status: str,
    working_tree_clean: bool,
    tests_ok: bool,
    scope_drift: bool,
    task: str,
    branch: str,
    default_branch: str,
) -> dict[str, str]:
    """Short rule-based blurbs; not prescriptive automation."""
    base = primary_status.split("+")[0]
    out: dict[str, str] = {}
    out["leave"] = "Keep the repo as-is after stop; use when you already parked manually or will continue immediately."
    out["wip"] = (
        f'Quickly save all tracked+untracked work: git add -A && git commit -m "WIP: {task}"'
    )
    out["stash"] = (
        f'Shelve everything (incl. untracked): git stash push -u -m "session: {task}"'
    )
    out["clean_commit"] = (
        f'Prepare a conventional commit on `{branch}` when tests pass and diff is ready: '
        f'git add -A && git commit -m "feat({branch}): {task}"'
    )
    if not tests_ok:
        out["note"] = "Tests failed — fix failures before a clean commit; leaving or WIP commit may still be OK locally."
    elif not working_tree_clean:
        out["note"] = "Uncommitted changes remain — prefer stash or WIP commit before switching branches."
    elif scope_drift:
        out["note"] = "Some edits were outside declared scope — review before merging."
    elif base == "clean_in_progress":
        out["note"] = f"Consider merging or opening a PR against `{default_branch}` when ready."
    else:
        out["note"] = "Session ended cleanly; no Git action required unless you want to delete the branch."
    return out


def build_stop_summary(
    repo_root: Path,
    session: dict[str, Any],
    test_result: TestRunResult | None,
    *,
    scope_entries: list[str] | None = None,
) -> StopSummary:
    initial_head = session.get("initial_head", "")
    files = git_ops.changed_files(repo_root)
    scope = scope_entries if scope_entries is not None else (session.get("scope") or [])
    drift_files = scope_drift_outside(repo_root, files, scope) if scope else []
    scope_drift_warning = bool(scope and drift_files)

    diff_stat = ""
    if initial_head:
        try:
            diff_stat = git_ops.diff_stat_range(repo_root, initial_head, "HEAD")
        except git_ops.GitError:
            diff_stat = git_ops.diff_stat(repo_root)
    else:
        diff_stat = git_ops.diff_stat(repo_root)

    commits_lines = git_ops.commits_since(repo_root, initial_head) if initial_head else []
    commits_detailed = git_ops.commits_since_detailed(repo_root, initial_head) if initial_head else []

    wt_clean = git_ops.is_working_tree_clean(repo_root)
    checkpoints = session.get("checkpoints") or []

    porcelain = git_ops.porcelain_summary(repo_root)
    ins, dels, tracked_files = (0, 0, 0)
    if initial_head:
        ins, dels, tracked_files = git_ops.diff_numstat_against_ref(repo_root, initial_head)

    status, next_action, cleanup = classify_work_state_v2(
        repo_root,
        initial_head,
        working_tree_clean=wt_clean,
        test_result=test_result,
        checkpoints=checkpoints,
        commits_since_start=commits_lines,
        _scope_drift=scope_drift_warning,
    )

    final_status = status
    if scope_drift_warning and status not in ("blocked_by_failing_tests",):
        next_action = (
            next_action + " Some changes were outside declared scope — review before merging."
        )

    tr_dict = test_result_to_dict(test_result)
    tests_ok = not tests_failed(test_result)

    parking = build_parking_recommendations(
        primary_status=status,
        working_tree_clean=wt_clean,
        tests_ok=tests_ok,
        scope_drift=scope_drift_warning,
        task=session.get("task", "task"),
        branch=session.get("branch", "branch"),
        default_branch=session.get("repo_default_branch") or "main",
    )

    branch = session.get("branch", "branch")
    task = session.get("task", "task")
    if status == "dirty_uncommitted" or status == "dirty_checkpointed":
        cleanup = [
            "git status",
            f'git add -A && git commit -m "WIP: {task}"',
            f'git stash push -u -m "wip: {task}"',
        ]
    elif status == "clean_in_progress":
        cleanup = [
            "git log --oneline -5",
            "# Optional (manual history edit):",
            "# git reset --soft main",
        ]

    return StopSummary(
        files_changed=files,
        diff_stat_session=diff_stat,
        commits_during_session=commits_lines,
        commits_detailed=commits_detailed,
        test_result=tr_dict,
        final_status=final_status,
        scope_drift_warning=scope_drift_warning,
        suggested_next_action=next_action,
        cleanup_suggestions=cleanup,
        parking_recommendations=parking,
        file_stats={
            "porcelain": porcelain,
            "diff_insertions": ins,
            "diff_deletions": dels,
            "tracked_files_changed": tracked_files,
            "untracked_count": len(git_ops.untracked_files(repo_root)),
        },
    )
