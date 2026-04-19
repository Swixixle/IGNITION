"""Rule-based end-of-session decisions: recommendations, risks, scorecard, grouping hints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ignition import git_ops
from ignition.config import IgnitionConfig
from ignition.tests import TestRunResult
from ignition.utils import parse_iso_duration_minutes, scope_drift_outside, scope_in_out_counts, utc_now_iso


def top_level_dirs(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for p in paths:
        p = p.replace("\\", "/").strip("./")
        if not p:
            continue
        parts = p.split("/", 1)
        out.add(parts[0] if parts[0] else ".")
    return out


def cluster_unrelated_paths(paths: list[str], threshold: int) -> bool:
    return len(top_level_dirs(paths)) >= threshold


def docs_code_tests_mix(paths: list[str]) -> bool:
    has_doc = any(
        re.search(r"(^|/)(docs?|doc)/", p.replace("\\", "/"), re.I) or p.lower().endswith(".md")
        for p in paths
    )
    has_code = any(p.endswith((".py", ".rs", ".go", ".ts", ".js", ".java")) for p in paths)
    has_test = any(
        re.search(r"(^|/)(tests?|test)/", p.replace("\\", "/"), re.I) or "/test_" in p for p in paths
    )
    return has_doc and has_code and has_test


def checkpoint_notes_diverse(checkpoints: list[dict[str, Any]]) -> bool:
    notes = [str(c.get("note", "")).strip() for c in checkpoints if c.get("note")]
    if len(notes) < 2:
        return False
    heads = {n.split()[0].lower() for n in notes if n}
    return len(heads) >= 2


def test_result_failed(tr: TestRunResult | dict[str, Any] | None) -> bool:
    if tr is None:
        return False
    if isinstance(tr, dict):
        if tr.get("skipped"):
            return False
        code = tr.get("exit_code")
        return code is not None and code != 0
    if tr.skipped:
        return False
    return tr.exit_code is not None and tr.exit_code != 0


def test_result_skipped(tr: TestRunResult | dict[str, Any] | None) -> bool:
    if tr is None:
        return True
    if isinstance(tr, dict):
        return bool(tr.get("skipped"))
    return bool(tr.skipped)


@dataclass
class DecisionBundle:
    primary_key: str
    secondary_keys: list[str]
    primary_reason: str
    secondary_reasons: list[str]
    recommendation_keys: list[str]
    risk_flags: list[str]
    split_changes_hint: bool
    split_changes_reason: str | None
    suggested_clean_message: str
    suggested_wip_message: str
    git_commands: list[str]
    scorecard: dict[str, Any]


def compute_risk_flags(
    cfg: IgnitionConfig,
    *,
    branch: str,
    default_branch: str,
    dirty: bool,
    tests_failed: bool,
    untracked_count: int,
    scope_drift_count: int,
    commit_count: int,
    started_at: str | None,
    last_checkpoint_at: str | None,
    pointer_stale: bool,
    branch_mismatch: bool,
) -> list[str]:
    flags: list[str] = []
    if branch == default_branch and dirty:
        flags.append("working_on_main_with_changes")
    if tests_failed:
        flags.append("failing_tests")
    if untracked_count >= cfg.large_untracked_threshold:
        flags.append("large_untracked_set")
    if scope_drift_count >= cfg.max_files_before_warning:
        flags.append("high_scope_drift")
    elif scope_drift_count > 0:
        flags.append("scope_drift_present")

    if started_at and last_checkpoint_at is None:
        mins = parse_iso_duration_minutes(started_at, utc_now_iso())
        if mins is not None and mins >= float(cfg.long_session_minutes):
            flags.append("no_checkpoint_for_long_session")

    if commit_count >= cfg.many_commits_threshold:
        flags.append("many_commits_for_single_session")
    if pointer_stale:
        flags.append("stale_active_session_pointer")
    if branch_mismatch:
        flags.append("branch_mismatch_with_session")
    return flags


def build_commit_message_suggestions(
    task: str,
    changed_files: list[str],
    scope: list[str],
) -> tuple[str, str]:
    dirs = sorted(top_level_dirs(changed_files))
    dom = ", ".join(dirs[:2]) if dirs else ""
    scope_bit = f" ({scope[0]})" if len(scope) == 1 else (" (scoped)" if scope else "")
    if dom:
        clean = f"{task}: {dom}{scope_bit}".strip()
    else:
        clean = f"{task}{scope_bit}".strip()
    wip = f"WIP: {task}"
    return (clean[:120], wip[:120])


def select_recommendations_v3(
    cfg: IgnitionConfig,
    *,
    working_tree_clean: bool,
    tests_failed: bool,
    tests_skipped: bool,
    in_scope: int,
    out_scope: int,
    changed_files: list[str],
    commit_count_since_start: int,
    on_default_branch: bool,
    split_hint: bool,
    conservative: bool,
) -> tuple[str, list[str], str, list[str]]:
    n_changed = len(changed_files)
    small_limit = 4 if conservative else 6

    if tests_failed:
        sec = ["make_wip_commit"] if not working_tree_clean else ["keep_working"]
        srs: list[str] = []
        if not working_tree_clean:
            srs.append(
                f"Tests failed with {n_changed} local file(s) changed; save with WIP or fix tests first."
            )
        return "fix_tests_first", sec, "Tests are failing — fix or narrow scope before a clean merge.", srs

    if split_hint:
        return (
            "split_changes_into_multiple_commits",
            ["review_before_merge", "make_wip_commit"],
            "Changes span multiple logical areas — split commits before merge.",
            ["Reduces review burden and revert risk."],
        )

    if out_scope > 0 and in_scope > 0:
        return (
            "clean_scope_before_commit",
            ["split_changes_into_multiple_commits", "review_before_merge"],
            f"{out_scope} file(s) out of declared scope — trim, widen scope, or split work.",
            [],
        )

    if on_default_branch and not working_tree_clean:
        return (
            "stash_and_switch",
            ["make_wip_commit"],
            "Uncommitted work on the default branch — prefer a feature branch or stash before sharing.",
            [],
        )

    if working_tree_clean and commit_count_since_start > 0 and not tests_failed:
        sec = ["keep_working"] if tests_skipped else []
        return (
            "review_before_merge",
            sec,
            "Session has commits and a clean tree — review the range, then open a PR or merge.",
            [],
        )

    if (
        not working_tree_clean
        and not tests_failed
        and out_scope == 0
        and n_changed <= small_limit
        and (not changed_files or in_scope >= n_changed)
    ):
        return (
            "safe_to_commit_cleanly",
            ["make_wip_commit"],
            f"Few in-scope files ({n_changed}); tests did not fail — OK for a clean commit if the task is done.",
            [],
        )

    if not working_tree_clean:
        return (
            "make_wip_commit",
            ["stash_and_switch"],
            f"{n_changed} file(s) still dirty — capture with WIP or stash before switching context.",
            [],
        )

    return (
        "keep_working",
        ["review_before_merge"],
        "No urgent stop signal — continue or checkpoint when ready.",
        [],
    )


def build_decision_bundle(
    repo_root: Path,
    cfg: IgnitionConfig,
    session: dict[str, Any] | None,
    test_result: TestRunResult | dict[str, Any] | None,
    *,
    pointer_stale: bool = False,
) -> DecisionBundle:
    sess = session or {}
    branch = git_ops.get_current_branch(repo_root)
    default_b = cfg.default_branch
    session_branch = sess.get("branch")
    branch_mismatch = bool(session_branch and session_branch != branch)

    changed = git_ops.changed_files(repo_root)
    dirty = not git_ops.is_working_tree_clean(repo_root)
    untracked = len(git_ops.untracked_files(repo_root))
    scope = sess.get("scope") or []
    inside, outside = scope_in_out_counts(repo_root, changed, scope) if scope else (len(changed), 0)
    drift_files = scope_drift_outside(repo_root, changed, scope) if scope else []

    initial_head = sess.get("initial_head") or ""
    commits = git_ops.commits_since(repo_root, initial_head) if initial_head else []

    tr_failed = test_result_failed(test_result)
    tr_skipped = test_result_skipped(test_result)

    split_hint = False
    split_reason: str | None = None
    if cluster_unrelated_paths(changed, cfg.split_change_directory_threshold):
        split_hint = True
        split_reason = (
            f"Files touch {len(top_level_dirs(changed))} top-level areas — likely multiple logical changes."
        )
    elif docs_code_tests_mix(changed):
        split_hint = True
        split_reason = "Docs, tests, and application code all touched — consider separate commits."
    elif len(drift_files) >= max(3, cfg.max_files_before_warning // 2):
        split_hint = True
        split_reason = "Several paths outside scope — may deserve a separate commit."
    elif checkpoint_notes_diverse(sess.get("checkpoints") or []):
        split_hint = True
        split_reason = "Checkpoint notes suggest different concerns."

    conservative = cfg.recommendation_mode == "conservative"

    pri, secs, pr, srs = select_recommendations_v3(
        cfg,
        working_tree_clean=not dirty,
        tests_failed=tr_failed,
        tests_skipped=tr_skipped,
        in_scope=inside,
        out_scope=outside,
        changed_files=changed,
        commit_count_since_start=len(commits),
        on_default_branch=branch == default_b,
        split_hint=split_hint,
        conservative=conservative,
    )

    if split_hint and pri != "split_changes_into_multiple_commits" and "split_changes_into_multiple_commits" not in secs:
        secs = (secs + ["split_changes_into_multiple_commits"])[:3]

    rec_keys = list(dict.fromkeys([pri, *secs]))

    risks = compute_risk_flags(
        cfg,
        branch=branch,
        default_branch=default_b,
        dirty=dirty,
        tests_failed=tr_failed,
        untracked_count=untracked,
        scope_drift_count=len(drift_files),
        commit_count=len(commits),
        started_at=sess.get("started_at"),
        last_checkpoint_at=sess.get("last_checkpoint_at"),
        pointer_stale=pointer_stale,
        branch_mismatch=branch_mismatch,
    )

    task = sess.get("task") or "session work"
    clean_msg, wip_msg = build_commit_message_suggestions(task, changed, scope)

    cmds: list[str] = []
    if pri == "fix_tests_first":
        cmds.append("# Fix failing tests, then re-run ignition recommend")
    if pri == "make_wip_commit":
        cmds.append(f'git add -A && git commit -m "{wip_msg}"')
    if pri == "stash_and_switch":
        slug = re.sub(r"[^a-z0-9]+", "-", task.lower())[:40].strip("-") or "work"
        cmds.append(f'git stash push -u -m "wip: {task}"')
        cmds.append(f"git checkout -b {cfg.default_feature_branch_prefix}{slug}")
    if pri == "safe_to_commit_cleanly":
        cmds.append(f'git add -A && git commit -m "{clean_msg}"')
    if pri == "review_before_merge":
        cmds.append("git log --oneline @{u}..HEAD  # review before PR")

    dur = None
    if sess.get("started_at"):
        dur = parse_iso_duration_minutes(sess["started_at"], utc_now_iso())

    scorecard = {
        "duration_minutes": dur,
        "files_changed": len(changed),
        "untracked_files": untracked,
        "commits_created": len(commits),
        "tests_passed": None
        if tr_skipped
        else (not tr_failed),
        "tests_failed": tr_failed,
        "tests_not_run": tr_skipped,
        "scope_drift_count": len(drift_files),
        "risk_flags_count": len(risks),
    }

    return DecisionBundle(
        primary_key=pri,
        secondary_keys=secs[:2],
        primary_reason=pr,
        secondary_reasons=srs,
        recommendation_keys=rec_keys,
        risk_flags=risks,
        split_changes_hint=split_hint,
        split_changes_reason=split_reason,
        suggested_clean_message=clean_msg,
        suggested_wip_message=wip_msg,
        git_commands=cmds,
        scorecard=scorecard,
    )


def bundle_to_dict(b: DecisionBundle) -> dict[str, Any]:
    return {
        "primary_recommendation": b.primary_key,
        "secondary_recommendations": b.secondary_keys,
        "primary_reason": b.primary_reason,
        "secondary_reasons": b.secondary_reasons,
        "recommendation_keys": b.recommendation_keys,
        "risk_flags": b.risk_flags,
        "split_changes_hint": b.split_changes_hint,
        "split_changes_reason": b.split_changes_reason,
        "suggested_clean_commit_message": b.suggested_clean_message,
        "suggested_wip_commit_message": b.suggested_wip_message,
        "suggested_git_commands": b.git_commands,
        "scorecard": b.scorecard,
    }
