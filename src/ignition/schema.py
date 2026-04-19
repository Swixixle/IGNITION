"""Session/receipt schema version and in-memory migration (files not rewritten unless export/migrate)."""

from __future__ import annotations

from typing import Any

from ignition import linkage as linkage_mod

# Bumped when on-disk shape changes meaningfully; migration normalizes older dicts at load time.
CURRENT_SESSION_SCHEMA_VERSION = 8
CURRENT_RECEIPT_SCHEMA_VERSION = 8


def migrate_session(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy migrated toward the latest session shape."""
    out = dict(data)
    raw_v = out.get("schema_version")
    try:
        v = int(raw_v) if raw_v is not None else 1
    except (TypeError, ValueError):
        v = 1

    out.setdefault("session_id", out.get("session_id", ""))
    out.setdefault("checkpoints", [])
    out.setdefault("snapshots", [])
    out.setdefault("recommend_events", [])
    out.setdefault("carryforward_todos", [])
    out.setdefault("carryforward_risks", [])
    out.setdefault("carryforward_questions", [])
    out.setdefault("carryforward_followups", [])
    out.setdefault("scope", out.get("scope") or [])

    if v < 7:
        out.setdefault("resumed_from_session_id", None)
    if v < 8:
        out.setdefault("repo_identity", out.get("repo_identity"))

    out["linkage"] = linkage_mod.normalize_linkage(out)

    if v > CURRENT_SESSION_SCHEMA_VERSION:
        out["schema_version"] = v
    else:
        out["schema_version"] = CURRENT_SESSION_SCHEMA_VERSION
    return out


def migrate_receipt(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize receipt JSON toward latest shape."""
    out = dict(data)
    raw_v = out.get("schema_version") or out.get("receipt_schema_version")
    try:
        v = int(raw_v) if raw_v is not None else 1
    except (TypeError, ValueError):
        v = 1
    out.setdefault("session", {})
    if v < 8:
        out.setdefault("linkage", {})
    if v > CURRENT_RECEIPT_SCHEMA_VERSION:
        out["schema_version"] = v
    else:
        out["schema_version"] = CURRENT_RECEIPT_SCHEMA_VERSION
    return out


def coerce_timestamp(s: str | None) -> str | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) < 8:
        return None
    return s
