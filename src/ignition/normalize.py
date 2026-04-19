"""Normalize session/receipt records across IGNITION versions for review and trends."""

from __future__ import annotations

from typing import Any

from ignition.decisions import top_level_dirs


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def wip_like_commit_count(commits_detailed: list[dict[str, Any]] | None, commits_lines: list[str] | None) -> int:
    n = 0
    for c in commits_detailed or []:
        msg = (c.get("message") or "").lower()
        if "wip" in msg or msg.startswith("wip:"):
            n += 1
    for line in commits_lines or []:
        if "wip" in line.lower():
            n += 1
    return n


def normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy with v4 longitudinal fields filled (defaults for old receipts).
    Accepts either a full receipt JSON or a minimal session dict.
    """
    out = dict(raw)
    session = out.get("session") or {}
    sid = session.get("session_id") or out.get("session_id") or ""

    files = out.get("files_changed") or []
    fc = out.get("files_changed_count")
    if fc is None:
        fc = len(files) if isinstance(files, list) else 0
    out["files_changed_count"] = _safe_int(fc, len(files) if isinstance(files, list) else 0)

    if not out.get("top_level_dirs_touched") and isinstance(files, list):
        out["top_level_dirs_touched"] = sorted(top_level_dirs(files))

    cps = out.get("checkpoints") or session.get("checkpoints")
    if cps is None:
        cps = []
    out["checkpoints_count"] = _safe_int(out.get("checkpoints_count"), len(cps))

    wic = out.get("wip_commit_count")
    if wic is None:
        wic = sum(1 for c in cps if c.get("wip_commit_hash"))
        wic += wip_like_commit_count(out.get("commits_detailed"), out.get("commits_during_session"))
    out["wip_commit_count"] = _safe_int(wic, 0)

    if out.get("final_action_taken") is None:
        out["final_action_taken"] = session.get("final_action_taken") or out.get("parking_used")

    dv3 = out.get("decisions_v3") or {}
    out.setdefault("recommendation_primary", dv3.get("primary_recommendation"))
    sec = dv3.get("secondary_recommendations")
    out.setdefault("recommendation_secondary", sec[0] if isinstance(sec, list) and sec else None)
    reasons = []
    if dv3.get("primary_reason"):
        reasons.append(dv3["primary_reason"])
    for s in dv3.get("secondary_reasons") or []:
        reasons.append(s)
    out.setdefault("recommendation_reasons", reasons or None)

    out.setdefault("clean_commit_suggestion", dv3.get("suggested_clean_commit_message"))
    out.setdefault("wip_commit_suggestion", dv3.get("suggested_wip_commit_message"))

    sc = out.get("session_scorecard") or {}
    out.setdefault("scope_drift_count", sc.get("scope_drift_count"))
    if out.get("scope_drift_count") is None:
        so = out.get("scope_out_count")
        out["scope_drift_count"] = _safe_int(so, 0) if so is not None else (1 if out.get("scope_drift_warning") else 0)

    rf = dv3.get("risk_flags") or out.get("risk_flags")
    if isinstance(rf, list):
        out["risk_flags"] = rf
    else:
        out.setdefault("risk_flags", [])

    tr = out.get("test_result")
    if out.get("tests_run") is None:
        out["tests_run"] = bool(tr and isinstance(tr, dict) and not tr.get("skipped"))
    if out.get("tests_passed") is None and tr and isinstance(tr, dict) and not tr.get("skipped"):
        out["tests_passed"] = tr.get("exit_code") == 0

    out.setdefault("final_status", out.get("final_status") or session.get("final_status"))

    out.setdefault("handoff_summary", out.get("handoff_summary"))
    out.setdefault("open_questions", out.get("open_questions"))
    out.setdefault("followups", out.get("followups"))
    out.setdefault("risks_noted", out.get("risks_noted"))
    out.setdefault("readiness_state", out.get("readiness_state"))
    out.setdefault("readiness_reasons", out.get("readiness_reasons"))
    out.setdefault("sessions_on_current_branch_count", out.get("sessions_on_current_branch_count"))

    for k in (
        "carryforward_todos",
        "carryforward_risks",
        "carryforward_questions",
        "carryforward_followups",
        "carryforward_summary",
        "carryforward_inherited",
    ):
        out.setdefault(k, out.get(k))

    return out


def is_session_receipt_file(name: str) -> bool:
    if not name.endswith(".json"):
        return False
    if name.startswith("recommend-"):
        return False
    if name.startswith("snapshot-"):
        return False
    if name.startswith("trends-"):
        return False
    if name.startswith("review-"):
        return False
    if name.startswith("handoff-"):
        return False
    return True
