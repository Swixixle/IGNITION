"""Session linkage: lightweight pointers between sessions and receipt artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def normalize_linkage(sess: dict[str, Any]) -> dict[str, Any]:
    """Merge linkage block with session-level fields (parent session, ids)."""
    raw = sess.get("linkage")
    base: dict[str, Any] = raw if isinstance(raw, dict) else {}
    sid = sess.get("session_id")
    parent = base.get("parent_session_id")
    if parent is None:
        parent = sess.get("resumed_from_session_id")

    rec_paths = base.get("recommend_receipt_paths")
    if not isinstance(rec_paths, list):
        rec_paths = []
    snap_paths = base.get("snapshot_receipt_paths")
    if not isinstance(snap_paths, list):
        snap_paths = []

    return {
        "session_id": base.get("session_id") or sid,
        "parent_session_id": parent,
        "handoff_receipt_path": base.get("handoff_receipt_path"),
        "stop_receipt_path": base.get("stop_receipt_path"),
        "recommend_receipt_paths": [str(x) for x in rec_paths if x],
        "snapshot_receipt_paths": [str(x) for x in snap_paths if x],
    }


def append_path_list(linkage: dict[str, Any], key: str, path: Path | str) -> None:
    p = str(path)
    cur = linkage.get(key)
    if not isinstance(cur, list):
        cur = []
        linkage[key] = cur
    if p and p not in cur:
        cur.append(p)
