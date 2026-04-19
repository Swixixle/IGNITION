"""Plain-language explanation of a single session — clear, not condescending."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ignition import session as session_mod
from ignition.normalize import normalize_record
from ignition.paths import receipt_dir


def load_session_payload(repo_root: Path, session_id: str, cfg_session: str | None, cfg_receipt: str | None) -> dict[str, Any] | None:
    """Prefer receipt JSON; fall back to session JSON."""
    rpath = receipt_dir(repo_root, cfg_receipt) / f"{session_id}.json"
    if rpath.is_file():
        try:
            raw = json.loads(rpath.read_text(encoding="utf-8"))
            if raw:
                sp = session_mod.session_file_path(repo_root, cfg_session, session_id)
                if sp.is_file():
                    sdata = session_mod.load_session_soft(sp)
                    if sdata:
                        raw.setdefault("checkpoints", sdata.get("checkpoints"))
                        raw.setdefault("final_action_taken", sdata.get("final_action_taken"))
                        raw.setdefault("recommend_events", sdata.get("recommend_events"))
                        raw.setdefault("snapshots", sdata.get("snapshots"))
                return normalize_record(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    sp = session_mod.session_file_path(repo_root, cfg_session, session_id)
    if sp.is_file():
        soft = session_mod.load_session_soft(sp)
        if soft:
            return normalize_record(soft)
    return None


def explain_session_text(r: dict[str, Any], *, plain_language: bool = False) -> str:
    r = normalize_record(r)
    sess = r.get("session") or {}
    repo = sess.get("repo_name", "this repository")
    branch = sess.get("branch", "unknown branch")
    task = sess.get("task", "unnamed task")
    started = sess.get("started_at", "")
    ended = sess.get("ended_at", "")
    dur = r.get("duration_minutes")

    lines: list[str] = []
    lines.append(f"Where: {repo}, branch {branch}.")
    lines.append(f"Task: {task}.")
    if dur is not None:
        lines.append(f"Duration: about {dur:.1f} minutes (start to session end).")
    elif started and ended:
        lines.append(f"Time span: {started} → {ended}.")

    fc = r.get("files_changed_count") or 0
    if plain_language:
        lines.append(f"What changed: about {fc} path(s) had local changes when the session ended.")
    else:
        lines.append(f"Files touched: {fc} path(s) with local changes at stop.")

    so = r.get("scope_out_count")
    si = r.get("scope_in_count")
    if si is not None and so is not None and (si + so) > 0:
        if plain_language and (so or 0) > 0:
            lines.append(
                "Scope: you listed certain areas; several changed files were outside that plan."
            )
        elif (so or 0) > 0:
            lines.append(f"Scope: {so} file(s) outside declared scope, {si} inside.")
        else:
            lines.append("Scope: changes stayed inside the areas you listed.")

    tr = r.get("test_result")
    if tr and isinstance(tr, dict) and not tr.get("skipped"):
        ok = tr.get("exit_code") == 0
        if plain_language:
            lines.append("Tests: a test command ran and " + ("passed." if ok else "failed."))
        else:
            lines.append(f"Tests: command ran, exit {tr.get('exit_code')} ({'pass' if ok else 'fail'}).")
    else:
        lines.append("Tests: no test run on the receipt, or tests were skipped.")

    fs = r.get("final_status") or "unknown"
    if plain_language:
        end_human = {
            "clean_complete": "ended with a clean tree and little or no extra commits.",
            "clean_in_progress": "ended clean, with commits from this session on the branch.",
            "dirty_uncommitted": "ended with uncommitted changes still present.",
            "dirty_checkpointed": "ended with a dirty tree, but you had checkpoints or commits saved earlier.",
            "blocked_by_failing_tests": "ended while tests were failing.",
        }.get(fs, f"ended with status {fs}.")
        lines.append(f"How it ended: {end_human}")
    else:
        lines.append(f"Final status: {fs}.")

    dv3 = r.get("decisions_v3") or {}
    pr = r.get("recommendation_primary") or dv3.get("primary_recommendation")
    if pr:
        reason = dv3.get("primary_reason", "")
        lines.append(f"IGNITION recommended: {pr}" + (f" — {reason}" if reason else ""))

    fa = r.get("final_action_taken")
    if fa:
        action_plain = {
            "leave": "At stop, you left the repo unchanged (no commit/stash from IGNITION).",
            "wip": "At stop, you recorded a WIP-style commit.",
            "commit": "At stop, you made a final-style commit.",
            "stash": "At stop, you stashed remaining work.",
            "note": "At stop, you only added a note.",
        }.get(fa, f"At stop, parking choice was: {fa}.")
        lines.append(action_plain)

    return "\n\n".join(lines)


def explain_session_json(r: dict[str, Any]) -> dict[str, Any]:
    r = normalize_record(r)
    return {
        "session_id": (r.get("session") or {}).get("session_id") or r.get("session_id"),
        "plain_summary": explain_session_text(r, plain_language=True),
        "technical_summary": explain_session_text(r, plain_language=False),
        "normalized": r,
    }
