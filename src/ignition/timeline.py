"""Single-session timeline for auditing without reading raw JSON."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ignition import explain as explain_mod
from ignition import session as session_mod


def load_timeline_session(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    session_id: str,
) -> dict[str, Any] | None:
    """Prefer live session file (checkpoints, recommend_events); merge receipt fields."""
    sp = session_mod.session_file_path(repo_root, cfg_session, session_id)
    base: dict[str, Any] = {}
    if sp.is_file():
        base = session_mod.load_session(sp)
    r = explain_mod.load_session_payload(repo_root, session_id, cfg_session, cfg_receipt)
    if r and base:
        merged = {**r, **base}
        for k in ("checkpoints", "snapshots", "recommend_events", "stopped_at", "ended_at", "status", "final_status"):
            if base.get(k) is not None:
                merged[k] = base[k]
        return merged
    if base:
        return base
    return r


def build_timeline(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered events: start, checkpoints, snapshots, recommend calls, stop."""
    events: list[dict[str, Any]] = []

    sid = session.get("session_id", "")
    started = session.get("started_at")
    if started:
        events.append(
            {
                "at": started,
                "type": "start",
                "detail": f"Session {sid} started",
            }
        )

    for cp in session.get("checkpoints") or []:
        at = cp.get("at", "")
        parts = []
        if cp.get("wip_commit_hash"):
            parts.append("wip commit")
        if cp.get("stash_message"):
            parts.append("stash")
        if cp.get("note"):
            parts.append("note")
        detail = ", ".join(parts) if parts else "checkpoint"
        note_preview = (cp.get("note") or "")[:80]
        if note_preview:
            detail = f"{detail}: {note_preview}"
        events.append({"at": at, "type": "checkpoint", "detail": detail})

    for sn in session.get("snapshots") or []:
        at = sn.get("at", "")
        events.append({"at": at, "type": "snapshot", "detail": "snapshot recorded"})

    for rec in session.get("recommend_events") or []:
        if isinstance(rec, dict) and rec.get("at"):
            pk = rec.get("primary_recommendation") or rec.get("primary") or ""
            events.append(
                {
                    "at": rec["at"],
                    "type": "recommend",
                    "detail": f"recommend → {pk}" if pk else "recommend",
                }
            )

    lr = session.get("last_recommend_at")
    if lr and not any(e.get("type") == "recommend" for e in events):
        events.append({"at": lr, "type": "recommend", "detail": "recommend (last)"})

    stopped = session.get("stopped_at") or session.get("ended_at")
    if stopped:
        st = session.get("status") or session.get("final_status") or ""
        events.append(
            {
                "at": stopped,
                "type": "stop",
                "detail": f"session ended ({st})" if st else "session ended",
            }
        )

    def sort_key(e: dict[str, Any]) -> str:
        return e.get("at") or ""

    events.sort(key=sort_key)
    return events
