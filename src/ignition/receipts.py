"""Session receipts: JSON artifacts and human-readable markdown flight logs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ignition.atomic_io import atomic_write_json, atomic_write_text
from ignition.schema import CURRENT_RECEIPT_SCHEMA_VERSION


def write_json_receipt(path: Path, payload: dict[str, Any]) -> None:
    pl = dict(payload)
    pl.setdefault("schema_version", CURRENT_RECEIPT_SCHEMA_VERSION)
    atomic_write_json(path, pl)


def format_markdown_receipt(
    payload: dict[str, Any],
    template_path: Path | None = None,
    *,
    style: str = "default",
) -> str:
    if template_path and template_path.is_file():
        try:
            raw = template_path.read_text(encoding="utf-8")
            body = _format_markdown_body(payload, style=style)
            if "{body}" in raw:
                return raw.replace("{body}", body)
            return raw + "\n\n" + body
        except OSError:
            pass
    return _format_markdown_body(payload, style=style)


def _file_limit(style: str) -> int:
    if style == "compact":
        return 25
    if style == "audit":
        return 500
    return 200


def _append_v3_sections(lines: list[str], payload: dict[str, Any], style: str) -> None:
    sc = payload.get("session_scorecard")
    if sc:
        lines.append("## Session scorecard (audit)")
        for k, v in sc.items():
            lines.append(f"- **{k}:** {v}")
        lines.append("")

    d = payload.get("decisions_v3")
    if not d:
        return

    lines.append("## Decision support")
    lines.append(f"- **Primary:** `{d.get('primary_recommendation', '')}` — {d.get('primary_reason', '')}")
    secs = d.get("secondary_recommendations") or []
    if secs:
        lines.append(f"- **Secondary:** {', '.join(f'`{s}`' for s in secs)}")
    srs = d.get("secondary_reasons") or []
    for s in srs:
        lines.append(f"  - {s}")
    risks = d.get("risk_flags") or []
    if risks:
        lines.append("- **Risk flags:**")
        for r in risks:
            lines.append(f"  - `{r}`")
    if d.get("split_changes_hint"):
        lines.append(f"- **Split changes hint:** {d.get('split_changes_reason', '')}")
    lines.append(f"- **Suggested clean commit:** `{d.get('suggested_clean_commit_message', '')}`")
    lines.append(f"- **Suggested WIP commit:** `{d.get('suggested_wip_commit_message', '')}`")
    cmds = d.get("suggested_git_commands") or []
    if cmds:
        lines.append("- **Suggested Git commands (not run):**")
        for c in cmds:
            lines.append(f"  - `{c}`")
    lines.append("")


def _format_markdown_body(payload: dict[str, Any], *, style: str = "default") -> str:
    lim = _file_limit(style)
    lines: list[str] = []
    title = "# IGNITION session receipt" if style != "compact" else "# IGNITION receipt (compact)"
    lines.append(title)
    lines.append("")
    meta = payload.get("session", {})
    lines.append("## Session")
    lines.append(f"- **Session ID:** {meta.get('session_id', '')}")
    if style == "audit":
        lines.append(f"- **Repository:** {meta.get('repo_name', '')}")
        lines.append(f"- **Root:** `{meta.get('repo_root', '')}`")
    elif style != "compact":
        lines.append(f"- **Repository:** {meta.get('repo_name', '')}")
        lines.append(f"- **Root:** `{meta.get('repo_root', '')}`")
    if meta.get("worktree_path") and style != "compact":
        lines.append(f"- **Worktree:** `{meta.get('worktree_path')}` ({meta.get('worktree_note', '')})")
    lines.append(f"- **Branch:** `{meta.get('branch', '')}`")
    if meta.get("repo_default_branch") and style != "compact":
        lines.append(f"- **Default branch (detected):** `{meta.get('repo_default_branch')}`")
    lines.append(f"- **Task:** {meta.get('task', '')}")
    scope = meta.get("scope") or []
    if not scope:
        lines.append("- **Scope:** *(not declared)*")
    elif style != "compact":
        lines.append("- **Scope:**")
        for s in scope[:20]:
            lines.append(f"  - `{s}`")
    else:
        lines.append(f"- **Scope:** {len(scope)} path(s)")
    lines.append(f"- **Definition of done:** {meta.get('definition_of_done', '')}")
    lines.append(f"- **Started:** {meta.get('started_at', '')}")
    if meta.get("ended_at"):
        lines.append(f"- **Ended:** {meta.get('ended_at', '')}")
    dur = payload.get("duration_minutes")
    if dur is not None:
        lines.append(f"- **Duration:** {dur:.1f} minutes")
    lines.append("")

    if style != "compact":
        lines.append("## Scope coverage (this session)")
        si = payload.get("scope_in_count")
        so = payload.get("scope_out_count")
        if si is not None and so is not None:
            lines.append(f"- **In scope:** {si} file(s)")
            lines.append(f"- **Out of scope:** {so} file(s)")
            prev = payload.get("scope_drift_preview") or []
            if prev:
                lines.append("- **Out of scope (sample):**")
                for p in prev[:10]:
                    lines.append(f"  - `{p}`")
        else:
            lines.append("- *(scope not used or no changes)*")
        lines.append("")

    lines.append("## Changes")
    fs = payload.get("file_stats") or {}
    por = fs.get("porcelain") or {}
    lines.append(f"- **Files touched (total):** {payload.get('files_changed_count', 0)}")
    if style != "compact":
        lines.append(
            f"- **Porcelain (approx):** added {por.get('added', 0)}, "
            f"modified {por.get('modified', 0)}, deleted {por.get('deleted', 0)}, "
            f"untracked {por.get('untracked', 0)}"
        )
        lines.append(
            f"- **Diff vs session start (tracked):** +{fs.get('diff_insertions', 0)} / -{fs.get('diff_deletions', 0)} "
            f"across {fs.get('tracked_files_changed', 0)} file(s)"
        )
    lines.append(f"- **Untracked (count):** {fs.get('untracked_count', 0)}")
    fc = payload.get("files_changed") or []
    if fc:
        lines.append("")
        for f in fc[:lim]:
            lines.append(f"- `{f}`")
        if len(fc) > lim:
            lines.append(f"- … and {len(fc) - lim} more")
    lines.append("")
    lines.append("### Diff stat (session)")
    lines.append("```")
    lines.append((payload.get("diff_stat_session") or "(none)").strip() or "(none)")
    lines.append("```")
    lines.append("")

    lines.append("## Commits during session")
    detailed = payload.get("commits_detailed") or []
    if detailed:
        for c in detailed[: 50 if style == "audit" else 20]:
            lines.append(f"- `{c.get('short', '')}` — {c.get('message', '')}")
    else:
        commits = payload.get("commits_during_session") or []
        if commits:
            for c in commits[:20]:
                lines.append(f"- `{c}`")
        else:
            lines.append("- *(none)*")
    lines.append("")

    tr = payload.get("test_result")
    lines.append("## Tests")
    if tr and isinstance(tr, dict) and not tr.get("skipped"):
        lines.append(f"- **Command:** `{tr.get('command', '')}`")
        lines.append(f"- **Exit code:** {tr.get('exit_code')}")
        passed = tr.get("exit_code") == 0
        lines.append(f"- **Result:** {'passed' if passed else 'failed'}")
        if style == "audit" and tr.get("stdout_summary"):
            lines.append("")
            lines.append("```")
            lines.append(tr["stdout_summary"][:6000])
            lines.append("```")
        elif tr.get("stdout_summary") and style == "default":
            lines.append("")
            lines.append("```")
            lines.append(tr["stdout_summary"][:3000])
            lines.append("```")
    else:
        lines.append("- *(not run or not configured)*")
    lines.append("")

    _append_v3_sections(lines, payload, style)

    lines.append("## Outcome")
    lines.append(f"- **Status:** `{payload.get('final_status', '')}`")
    if payload.get("scope_drift_warning"):
        lines.append("- **Scope drift:** yes (review before merging)")
    lines.append(f"- **Suggested next action:** {payload.get('suggested_next_action', '')}")
    pr = payload.get("parking_recommendations") or {}
    if pr and style != "compact":
        lines.append("")
        lines.append("### Parking (rule-based hints)")
        for key in ("leave", "wip", "stash", "clean_commit", "note"):
            if key in pr:
                lines.append(f"- **{key}:** {pr[key]}")
    if payload.get("cleanup_suggestions"):
        lines.append("")
        lines.append("### Suggested Git commands (manual review)")
        for cmd in payload["cleanup_suggestions"]:
            lines.append(f"- `{cmd}`")
    lines.append("")
    lines.append("---")
    lines.append("*IGNITION records local session boundaries — it does not replace Git.*")
    lines.append("")
    return "\n".join(lines)


def write_markdown_receipt(
    path: Path,
    payload: dict[str, Any],
    template_path: Path | None = None,
    *,
    style: str = "default",
) -> None:
    atomic_write_text(path, format_markdown_receipt(payload, template_path, style=style))
