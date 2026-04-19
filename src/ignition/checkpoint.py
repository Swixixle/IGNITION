"""Checkpoint record construction."""

from __future__ import annotations

from typing import Any

from ignition.utils import utc_now_iso


def make_checkpoint_record(
    *,
    changed_files: list[str],
    diff_stat: str,
    test_result: dict[str, Any] | None,
    wip_commit_hash: str | None,
    stash_message: str | None,
    note: str | None,
    head_hash: str,
    note_tags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "at": utc_now_iso(),
        "changed_files": changed_files,
        "diff_stat": diff_stat,
        "test_result": test_result,
        "wip_commit_hash": wip_commit_hash,
        "stash_message": stash_message,
        "note": note or "",
        "note_tags": note_tags or {"todo": [], "risk": [], "question": [], "followup": []},
        "head_hash": head_hash,
    }
