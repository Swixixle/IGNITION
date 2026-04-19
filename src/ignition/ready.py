"""Rule-based merge/review readiness — hints only, not proof."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ignition import git_ops
from ignition.config import IgnitionConfig
from ignition import decisions as decisions_mod
ReadinessState = Literal["not_ready", "review_ready", "merge_ready_candidate"]


@dataclass
class ReadinessAssessment:
    state: ReadinessState
    reasons: list[str]
    summary_line: str


def assess_readiness(
    repo_root: Path,
    cfg: IgnitionConfig,
    session: dict[str, Any] | None,
    *,
    test_result_dict: dict[str, Any] | None,
    final_status: str,
    files_changed: list[str],
    scope_out_count: int,
    bundle: decisions_mod.DecisionBundle,
    working_tree_clean: bool,
) -> ReadinessAssessment:
    """Heuristic readiness; never claims certainty."""
    reasons: list[str] = []
    branch = session.get("branch") if session else None
    default_b = cfg.default_branch
    primary = bundle.primary_key
    n_files = len(files_changed)

    tr_failed = False
    tr_skipped = True
    if test_result_dict and isinstance(test_result_dict, dict):
        tr_skipped = bool(test_result_dict.get("skipped"))
        if not tr_skipped:
            tr_failed = test_result_dict.get("exit_code") not in (0, None)

    if tr_failed:
        reasons.append("tests did not pass")
    if not working_tree_clean:
        reasons.append("working tree is not clean")
    if final_status == "blocked_by_failing_tests":
        reasons.append("session ended with failing tests")

    heavy_drift = scope_out_count >= cfg.max_files_before_warning
    some_drift = scope_out_count > 0 and not heavy_drift
    if heavy_drift:
        reasons.append("many files outside declared scope")

    if bundle.split_changes_hint:
        reasons.append("unrelated change groups detected (split before review)")

    if primary in ("fix_tests_first", "make_wip_commit") and working_tree_clean is False:
        reasons.append("recommendation expects cleanup before review")

    on_default = branch == default_b if branch else True
    if on_default and not working_tree_clean:
        reasons.append("on default branch with uncommitted changes")

    # not_ready: hard blockers
    if tr_failed or final_status == "blocked_by_failing_tests":
        return ReadinessAssessment(
            state="not_ready",
            reasons=reasons or ["tests failing"],
            summary_line="Not ready: failing tests and/or blocked session state.",
        )

    if not working_tree_clean:
        return ReadinessAssessment(
            state="not_ready",
            reasons=reasons,
            summary_line="Not ready: uncommitted work remains.",
        )

    if heavy_drift or bundle.split_changes_hint:
        return ReadinessAssessment(
            state="not_ready",
            reasons=reasons,
            summary_line="Not ready: too many out-of-scope or unrelated changes; split before review.",
        )

    if tr_skipped:
        reasons.append("tests were not run or were skipped")

    # merge_ready_candidate: strict
    merge_ok = (
        not on_default
        and working_tree_clean
        and not tr_failed
        and not tr_skipped
        and final_status in ("clean_complete", "clean_in_progress")
        and not heavy_drift
        and not bundle.split_changes_hint
        and primary in ("safe_to_commit_cleanly", "review_before_merge")
        and n_files <= max(cfg.max_files_before_warning * 2, 24)
    )

    if merge_ok:
        sl = (
            "Merge-ready candidate: tests pass, tree clean, scope mostly in bounds, "
            "no major split risk — verify in review anyway."
        )
        return ReadinessAssessment(state="merge_ready_candidate", reasons=[], summary_line=sl)

    # review_ready: softer bar
    review_ok = (
        working_tree_clean
        and not tr_failed
        and final_status not in ("blocked_by_failing_tests", "dirty_uncommitted")
        and not heavy_drift
    )

    if review_ok:
        extra = []
        if some_drift:
            extra.append("some scope drift")
        if tr_skipped:
            extra.append("tests skipped")
        rsn = reasons + extra
        sl = (
            "Review-ready candidate: tests pass and tree clean"
            + ("; note: " + "; ".join(rsn) if rsn else "")
            + "."
        )
        return ReadinessAssessment(state="review_ready", reasons=rsn, summary_line=sl)

    return ReadinessAssessment(
        state="not_ready",
        reasons=reasons or ["state does not meet review bar"],
        summary_line="Not ready: address risks, scope, or tests before review.",
    )


def assess_live_session(
    repo_root: Path,
    cfg: IgnitionConfig,
    session: dict[str, Any],
    *,
    bundle: decisions_mod.DecisionBundle,
    test_result_dict: dict[str, Any] | None,
) -> ReadinessAssessment:
    """Readiness for an active session (e.g. `ignition ready` before stop)."""
    changed = git_ops.changed_files(repo_root)
    scope_list = session.get("scope") or []
    from ignition.utils import scope_in_out_counts

    _si, so = scope_in_out_counts(repo_root, changed, scope_list)
    working_tree_clean = git_ops.is_working_tree_clean(repo_root)

    tr_failed = False
    tr_skipped = True
    if test_result_dict and isinstance(test_result_dict, dict):
        tr_skipped = bool(test_result_dict.get("skipped"))
        if not tr_skipped:
            tr_failed = test_result_dict.get("exit_code") not in (0, None)

    # Infer pseudo final_status from tree
    if tr_failed:
        fs = "blocked_by_failing_tests"
    elif not working_tree_clean:
        fs = "dirty_uncommitted"
    else:
        fs = "clean_in_progress"

    return assess_readiness(
        repo_root,
        cfg,
        session,
        test_result_dict=test_result_dict,
        final_status=fs,
        files_changed=changed,
        scope_out_count=so,
        bundle=bundle,
        working_tree_clean=working_tree_clean,
    )
