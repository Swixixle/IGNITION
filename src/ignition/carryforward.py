"""Carry-forward context between sessions (local metadata only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ignition import git_ops
from ignition import hygiene as hygiene_mod
from ignition import session as session_mod


def merge_amended_into_tag_agg(session: dict[str, Any], tag_agg: dict[str, Any]) -> None:
    """Fold session lists edited via `amend-context` into aggregated tag buckets."""
    pairs = [
        ("carryforward_todos", "todos_noted"),
        ("carryforward_risks", "risks_noted"),
        ("carryforward_questions", "open_questions"),
        ("carryforward_followups", "followups"),
    ]
    for s_key, t_key in pairs:
        extra = session.get(s_key)
        if not extra:
            continue
        if not isinstance(extra, list):
            continue
        cur = tag_agg.get(t_key) or []
        tag_agg[t_key] = list(dict.fromkeys(list(cur) + [str(x) for x in extra if x]))


def build_carryforward_block(
    *,
    tag_agg: dict[str, Any],
    stop_note: str,
    handoff_summary: str,
    suggested_next_action: str,
    recommendation_primary: str | None,
    session_carryforward_summary: str | None = None,
) -> dict[str, Any]:
    """Normalized block stored on session at stop and echoed by `next` / `begin`."""
    todos = list(tag_agg.get("todos_noted") or tag_agg.get("todos") or [])
    risks = list(tag_agg.get("risks_noted") or [])
    questions = list(tag_agg.get("open_questions") or [])
    followups = list(tag_agg.get("followups") or [])

    summary_parts = [handoff_summary]
    if session_carryforward_summary and str(session_carryforward_summary).strip():
        summary_parts.insert(0, str(session_carryforward_summary).strip())
    if suggested_next_action:
        summary_parts.append(f"Next: {suggested_next_action}")
    if recommendation_primary:
        summary_parts.append(f"Suggested focus: {recommendation_primary}")
    cf_summary = " ".join(s for s in summary_parts if s).strip()

    return {
        "carryforward_todos": todos,
        "carryforward_risks": risks,
        "carryforward_questions": questions,
        "carryforward_followups": followups,
        "carryforward_summary": cf_summary,
        "carryforward_suggested_next": suggested_next_action,
        "carryforward_primary_recommendation": recommendation_primary,
        "carryforward_stop_note": stop_note.strip() if stop_note else "",
    }


def find_latest_stopped_session(
    repo_root: Path,
    session_rel: str | None,
    *,
    branch: str | None = None,
) -> dict[str, Any] | None:
    """Most recently stopped session for this repo (optional branch filter)."""
    rr = str(repo_root.resolve())
    best: tuple[str, dict[str, Any]] | None = None
    for path in session_mod.iter_session_json_paths(repo_root, session_rel):
        data = session_mod.load_session_soft(path)
        if data is None:
            continue
        if data.get("repo_root") != rr:
            continue
        if data.get("status") not in ("stopped", "stale_closed"):
            continue
        if not data.get("stopped_at") and not data.get("ended_at"):
            continue
        if branch and data.get("branch") != branch:
            continue
        st = data.get("stopped_at") or data.get("ended_at") or ""
        if best is None or st > best[0]:
            best = (st, data)
    return best[1] if best else None


def build_next_payload(
    repo_root: Path,
    cfg,
    *,
    branch: str | None,
) -> dict[str, Any]:
    """Payload for `ignition next` — short carry-forward from last stopped work on branch (or repo)."""
    br: str | None = branch
    if br is None:
        b = git_ops.get_current_branch_safe(repo_root)
        br = None if b == "(unknown)" else b
    prev = find_latest_stopped_session(repo_root, cfg.session_dir, branch=br)
    hints: list[str] = []
    if br:
        hints = hygiene_mod.branch_hygiene_hints(
            repo_root,
            cfg.session_dir,
            branch=br,
            default_branch=cfg.default_branch,
            session_data=None,
        )
    if not prev:
        return {
            "repo": repo_root.name,
            "branch": br,
            "prior_session_id": None,
            "message": "No prior stopped session found for this branch.",
            "branch_hygiene_hints": hints,
        }

    cf_todos = prev.get("carryforward_todos") or []
    cf_risks = prev.get("carryforward_risks") or []
    cf_q = prev.get("carryforward_questions") or []
    cf_fu = prev.get("carryforward_followups") or []
    cf_sum = prev.get("carryforward_summary") or ""

    return {
        "repo": repo_root.name,
        "repo_root": str(repo_root.resolve()),
        "branch": br or prev.get("branch"),
        "prior_session_id": prev.get("session_id"),
        "prior_task": prev.get("task"),
        "how_it_ended": prev.get("final_status"),
        "suggested_next_from_prior": prev.get("suggested_next_action") or prev.get("carryforward_suggested_next"),
        "carryforward_todos": cf_todos[:12],
        "carryforward_risks": cf_risks[:12],
        "carryforward_questions": cf_q[:12],
        "carryforward_followups": cf_fu[:12],
        "carryforward_summary": cf_sum,
        "branch_hygiene_hints": hints,
    }


def inherited_block_from_prior(prior: dict[str, Any]) -> dict[str, Any]:
    """Store on a new session after `begin` (optional)."""
    return {
        "from_session_id": prior.get("session_id"),
        "carryforward_todos": (prior.get("carryforward_todos") or [])[:15],
        "carryforward_risks": (prior.get("carryforward_risks") or [])[:15],
        "carryforward_questions": (prior.get("carryforward_questions") or [])[:15],
        "carryforward_followups": (prior.get("carryforward_followups") or [])[:15],
        "carryforward_summary": prior.get("carryforward_summary"),
        "suggested_next": prior.get("carryforward_suggested_next") or prior.get("suggested_next_action"),
    }


def format_next_human(payload: dict[str, Any], *, plain: bool = True) -> str:
    """Short, plain lines for `ignition next` and similar."""
    if payload.get("prior_session_id") is None and payload.get("message"):
        return str(payload.get("message"))

    lines: list[str] = []
    lines.append(f"Last session: {payload.get('prior_task', '')} (ended: {payload.get('how_it_ended', 'unknown')})")
    if payload.get("carryforward_summary"):
        lines.append(f"Summary: {payload['carryforward_summary'][:300]}")
    if payload.get("suggested_next_from_prior"):
        lines.append(f"Suggested next: {payload['suggested_next_from_prior']}")
    for label, key in (
        ("Todos", "carryforward_todos"),
        ("Risks", "carryforward_risks"),
        ("Questions", "carryforward_questions"),
        ("Follow-ups", "carryforward_followups"),
    ):
        items = payload.get(key) or []
        if items:
            lines.append(f"{label}: " + "; ".join(items[:6]))
    hints = payload.get("branch_hygiene_hints") or []
    if hints:
        lines.append("Branch: " + hints[0])
    return "\n".join(lines)
