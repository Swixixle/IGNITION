"""Optional structured tags inside free-form checkpoint/stop notes (todo:, risk:, …)."""

from __future__ import annotations

import re
from typing import Any

_TAG_LINE = re.compile(
    r"^(?P<tag>todo|risk|question|followup)\s*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)


def parse_note_tags(text: str) -> dict[str, list[str]]:
    """Parse lines like `risk: flaky integration` into buckets. Unknown lines ignored."""
    buckets: dict[str, list[str]] = {
        "todo": [],
        "risk": [],
        "question": [],
        "followup": [],
    }
    if not text or not text.strip():
        return buckets
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _TAG_LINE.match(line)
        if not m:
            continue
        tag = m.group("tag").lower()
        rest = (m.group("rest") or "").strip()
        if tag in buckets and rest:
            buckets[tag].append(rest)
    return buckets


def merge_tag_dicts(*dicts: dict[str, list[str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"todo": [], "risk": [], "question": [], "followup": []}
    for d in dicts:
        for k, vs in (d or {}).items():
            if k in out and isinstance(vs, list):
                out[k].extend(vs)
    return out


def aggregate_checkpoint_tags(checkpoints: list[dict[str, Any]]) -> dict[str, list[str]]:
    merged = merge_tag_dicts()
    for cp in checkpoints or []:
        nt = cp.get("note_tags")
        if isinstance(nt, dict):
            merged = merge_tag_dicts(merged, {k: list(v) if isinstance(v, list) else [] for k, v in nt.items()})
        else:
            note = str(cp.get("note") or "")
            merged = merge_tag_dicts(merged, parse_note_tags(note))
    return merged


def aggregate_session_notes(
    checkpoints: list[dict[str, Any]],
    stop_note: str = "",
    stop_note_tags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Combined structured tags + flat lists for receipts."""
    from_cp = aggregate_checkpoint_tags(checkpoints)
    stop_tags = stop_note_tags if stop_note_tags else parse_note_tags(stop_note)
    combined = merge_tag_dicts(from_cp, stop_tags)
    return {
        "note_tags": combined,
        "open_questions": combined["question"],
        "followups": combined["followup"],
        "risks_noted": combined["risk"],
        "todos_noted": combined["todo"],
    }
