"""Handoff markdown + JSON for reviewers and future sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ignition.atomic_io import atomic_write_json, atomic_write_text
from ignition import explain as explain_mod
from ignition import hygiene as hygiene_mod
from ignition import session as session_mod
from ignition.normalize import normalize_record
from ignition.notes_tags import aggregate_session_notes
from ignition.paths import receipt_dir
from ignition.utils import utc_now_iso


def _pr_summary_line(task: str, branch: str, primary: str | None) -> str:
    p = primary or "session"
    return f"[{branch}] {task} — {p}"


def build_handoff_payload(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    record: dict[str, Any],
    *,
    default_branch: str = "main",
) -> dict[str, Any]:
    r = normalize_record(dict(record))
    sess = r.get("session") or {}
    dv3 = r.get("decisions_v3") or {}
    primary = r.get("recommendation_primary") or dv3.get("primary_recommendation")
    cps = r.get("checkpoints") or sess.get("checkpoints") or []
    agg = aggregate_session_notes(cps, "", None)

    handoff_summary = (
        f"{sess.get('repo_name', 'repo')} / {sess.get('branch', '')} — {sess.get('task', '')}. "
        f"Status: {r.get('final_status', 'unknown')}."
    )

    br = str(sess.get("branch") or "")
    hy_hints = hygiene_mod.branch_hygiene_hints(
        repo_root,
        cfg_session,
        branch=br,
        default_branch=default_branch,
        session_data=sess if isinstance(sess, dict) else None,
    )
    soc = hygiene_mod.sessions_on_branch_for_receipt(repo_root, cfg_session, br)

    cf_todos = r.get("carryforward_todos") or []
    cf_sum_extra = r.get("carryforward_summary")

    payload = {
        "generated_at": utc_now_iso(),
        "kind": "handoff",
        "session_id": sess.get("session_id") or r.get("session_id"),
        "repo": sess.get("repo_name"),
        "repo_root": sess.get("repo_root"),
        "branch": sess.get("branch"),
        "task": sess.get("task"),
        "scope": sess.get("scope") or [],
        "definition_of_done": sess.get("definition_of_done"),
        "files_changed_count": r.get("files_changed_count"),
        "files_changed": r.get("files_changed") or [],
        "test_result": r.get("test_result"),
        "scope_drift_warning": r.get("scope_drift_warning"),
        "scope_in_count": r.get("scope_in_count"),
        "scope_out_count": r.get("scope_out_count"),
        "risk_flags": r.get("risk_flags") or [],
        "recommendation_primary": primary,
        "recommendation_reasons": r.get("recommendation_reasons"),
        "suggested_next_action": r.get("suggested_next_action"),
        "suggested_pr_title": _pr_summary_line(
            str(sess.get("task", "task")),
            str(sess.get("branch", "")),
            primary,
        ),
        "open_questions": agg["open_questions"],
        "followups": agg["followups"],
        "risks_noted": agg["risks_noted"],
        "todos_noted": agg["todos_noted"],
        "handoff_summary": handoff_summary,
        "readiness_state": r.get("readiness_state"),
        "readiness_reasons": r.get("readiness_reasons"),
        "branch_hygiene_hints": hy_hints,
        "sessions_on_current_branch_count": soc,
        "carryforward_todos": cf_todos,
        "carryforward_summary_extra": cf_sum_extra,
        "carryforward_inherited": r.get("carryforward_inherited"),
    }
    return payload


def render_handoff_markdown(p: dict[str, Any]) -> str:
    lines: list[str] = [
        f"# Handoff — {p.get('task', 'session')}",
        "",
        f"- **Repo:** {p.get('repo')} (`{p.get('repo_root')}`)",
        f"- **Branch:** {p.get('branch')}",
        f"- **Session ID:** `{p.get('session_id')}`",
        "",
        "## Intent",
        "",
        f"**Scope:** {', '.join(p.get('scope') or []) or '(not set)'}",
        "",
        "## What changed",
        "",
        f"- Files touched: {p.get('files_changed_count', 0)}",
    ]
    tr = p.get("test_result")
    if tr and isinstance(tr, dict) and not tr.get("skipped"):
        lines.append(f"- Tests: exit {tr.get('exit_code')} ({'pass' if tr.get('exit_code') == 0 else 'fail'})")
    else:
        lines.append("- Tests: not run or skipped")

    if p.get("scope_out_count", 0) or p.get("scope_drift_warning"):
        lines.extend(["", "## Scope / drift", "", f"- Out of scope files: {p.get('scope_out_count', 0)}"])
        if p.get("scope_drift_warning"):
            lines.append(f"- Warning: {p['scope_drift_warning']}")

    lines.extend(
        [
            "",
            "## Risks (automated flags)",
            "",
        ]
    )
    for rf in p.get("risk_flags") or []:
        lines.append(f"- {rf}")
    if not p.get("risk_flags"):
        lines.append("- (none flagged)")

    lines.extend(
        [
            "",
            "## Recommendations",
            "",
            f"- Primary: `{p.get('recommendation_primary')}`",
            f"- Next action: {p.get('suggested_next_action')}",
            "",
            "## Suggested PR / summary line",
            "",
            f"`{p.get('suggested_pr_title')}`",
            "",
        ]
    )

    oq = p.get("open_questions") or []
    fu = p.get("followups") or []
    rk = p.get("risks_noted") or []
    td = p.get("todos_noted") or []
    if oq or fu or rk or td:
        lines.extend(["## Notes from checkpoints", ""])
        for t in td:
            lines.append(f"- **todo:** {t}")
        for r in rk:
            lines.append(f"- **risk:** {r}")
        for q in oq:
            lines.append(f"- **question:** {q}")
        for f in fu:
            lines.append(f"- **followup:** {f}")
        lines.append("")

    cft = p.get("carryforward_todos") or []
    cfs = p.get("carryforward_summary_extra")
    inh = p.get("carryforward_inherited")
    if cft or cfs or inh:
        lines.extend(["## Carry-forward", ""])
        if cfs:
            lines.append(f"- {cfs}")
        for t in cft[:12]:
            lines.append(f"- todo: {t}")
        if inh and isinstance(inh, dict) and inh.get("from_session_id"):
            lines.append(f"- (inherited context from `{inh.get('from_session_id')}`)")
        lines.append("")

    bh = p.get("branch_hygiene_hints") or []
    if bh:
        lines.extend(["## Branch hygiene (hints only)", ""])
        for h in bh:
            lines.append(f"- {h}")
        lines.append("")
    soc = p.get("sessions_on_current_branch_count")
    if soc is not None:
        lines.extend([f"- Sessions recorded on this branch: {soc}", ""])

    lines.extend(["## Readiness (heuristic)", "", f"- State: `{p.get('readiness_state')}`", ""])

    return "\n".join(lines).rstrip() + "\n"


def write_handoff_artifacts(
    repo_root: Path,
    cfg_receipt: str | None,
    session_id: str,
    payload: dict[str, Any],
) -> tuple[Path, Path]:
    rdir = receipt_dir(repo_root, cfg_receipt)
    rdir.mkdir(parents=True, exist_ok=True)
    md_path = rdir / f"handoff-{session_id}.md"
    js_path = rdir / f"handoff-{session_id}.json"
    atomic_write_text(md_path, render_handoff_markdown(payload))
    atomic_write_json(js_path, payload)
    return md_path, js_path


def resolve_handoff_record(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    *,
    session_id: str | None,
    use_current: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (record, error_message)."""
    if use_current:
        sp = session_mod.read_active_session_file(repo_root, cfg_session)
        if not sp:
            return None, "No active session."
        data = session_mod.load_session(sp)
        sid = data.get("session_id")
        if not sid:
            return None, "Session has no id."
        loaded = explain_mod.load_session_payload(repo_root, sid, cfg_session, cfg_receipt)
        if loaded:
            return loaded, None
        return normalize_record(data), None

    if session_id:
        loaded = explain_mod.load_session_payload(repo_root, session_id, cfg_session, cfg_receipt)
        if loaded:
            return loaded, None
        return None, f"No session or receipt for `{session_id}`."

    # Latest: most recent session file for repo
    rr = str(repo_root.resolve())
    best: tuple[str, dict[str, Any]] | None = None
    for path in session_mod.iter_session_json_paths(repo_root, cfg_session):
        data = session_mod.load_session_soft(path)
        if data is None:
            continue
        if data.get("repo_root") != rr:
            continue
        st = data.get("started_at") or ""
        if best is None or st > best[0]:
            best = (st, data)
    if not best:
        return None, "No sessions found."
    sid = best[1].get("session_id", "")
    loaded = explain_mod.load_session_payload(repo_root, sid, cfg_session, cfg_receipt)
    if loaded:
        return loaded, None
    return normalize_record(best[1]), None
