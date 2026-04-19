"""Aggregate review of recent sessions — deterministic patterns, no coaching persona."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ignition.atomic_io import atomic_write_json
from ignition import session as session_mod
from ignition.normalize import is_session_receipt_file, normalize_record
from ignition.paths import receipt_dir
from ignition.utils import utc_now_iso


def _parse_start(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def iter_session_records(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    *,
    all_repos: bool,
) -> list[dict[str, Any]]:
    """Load normalized records from receipt JSONs, optionally enriched from session files."""
    rr = str(repo_root.resolve())
    rdir = receipt_dir(repo_root, cfg_receipt)
    out: list[dict[str, Any]] = []
    if not rdir.is_dir():
        return out

    for path in sorted(rdir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not is_session_receipt_file(path.name):
            continue
        raw = _load_json(path)
        if not raw:
            continue
        sess = raw.get("session") or {}
        if raw.get("phase") == "started" and not sess.get("ended_at") and not raw.get("final_status"):
            continue
        if not all_repos and sess.get("repo_root") and sess["repo_root"] != rr:
            continue
        merged = dict(raw)
        sid = sess.get("session_id") or merged.get("session_id")
        if sid:
            sp = session_mod.session_file_path(repo_root, cfg_session, sid)
            if sp.is_file():
                sdata = session_mod.load_session_soft(sp)
                if sdata:
                    merged.setdefault("checkpoints", sdata.get("checkpoints"))
                    merged.setdefault("final_action_taken", sdata.get("final_action_taken"))
        out.append(normalize_record(merged))
    return out


def filter_by_days(records: list[dict[str, Any]], days: int | None) -> list[dict[str, Any]]:
    if days is None or days <= 0:
        return records
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[dict[str, Any]] = []
    for r in records:
        sess = r.get("session") or {}
        st = sess.get("started_at") or r.get("started_at")
        dt = _parse_start(st)
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= cutoff:
            kept.append(r)
    return kept


def filter_by_session_limit(records: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if not limit or limit <= 0:
        return records
    # already usually reverse chrono from iter; sort by started_at
    def key(r: dict[str, Any]) -> str:
        s = (r.get("session") or {}).get("started_at") or r.get("started_at") or ""
        return s

    sorted_r = sorted(records, key=key, reverse=True)
    return sorted_r[:limit]


def build_review(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    *,
    days: int = 7,
    sessions_limit: int | None = None,
    all_repos: bool = False,
) -> dict[str, Any]:
    records = iter_session_records(repo_root, cfg_session, cfg_receipt, all_repos=all_repos)
    records = filter_by_days(records, days)
    records = filter_by_session_limit(records, sessions_limit)

    n = len(records)
    if n == 0:
        return {
            "session_count": 0,
            "period_days": days,
            "summary": "No stopped sessions in range with receipt data.",
            "patterns_noticed": [],
            "metrics": {},
        }

    durations = []
    files_counts = []
    untracked_counts = []
    tests_run = 0
    tests_pass = 0
    tests_fail = 0
    tests_skip = 0
    status_counts: Counter[str] = Counter()
    drift_sessions = 0
    wip_endings = 0
    clean_endings = 0
    actions: Counter[str] = Counter()
    top_dirs: Counter[str] = Counter()
    next_actions: Counter[str] = Counter()
    prim_recs: Counter[str] = Counter()

    for r in records:
        sess = r.get("session") or {}
        st = sess.get("started_at")
        en = sess.get("ended_at")
        if st and en:
            d0 = _parse_start(st)
            d1 = _parse_start(en)
            if d0 and d1:
                durations.append((d1 - d0).total_seconds() / 60.0)

        files_counts.append(r.get("files_changed_count") or 0)
        fs = r.get("file_stats") or {}
        untracked_counts.append(fs.get("untracked_count") or 0)

        tr = r.get("test_result")
        if tr and isinstance(tr, dict) and not tr.get("skipped"):
            tests_run += 1
            if tr.get("exit_code") == 0:
                tests_pass += 1
            else:
                tests_fail += 1
        else:
            tests_skip += 1

        fs_stat = r.get("final_status") or "unknown"
        status_counts[fs_stat] += 1

        if r.get("scope_drift_warning") or (r.get("scope_drift_count") or 0) > 0:
            drift_sessions += 1

        fa = r.get("final_action_taken") or "leave"
        actions[fa] += 1
        if fa in ("wip", "commit") or "wip" in str(fa).lower():
            wip_endings += 1
        if fs_stat in ("clean_complete", "clean_in_progress") and fa == "leave":
            clean_endings += 1

        sna = r.get("suggested_next_action") or ""
        if sna:
            next_actions[sna[:120]] += 1

        pr = r.get("recommendation_primary") or (r.get("decisions_v3") or {}).get("primary_recommendation")
        if pr:
            prim_recs[pr] += 1

        for d in r.get("top_level_dirs_touched") or []:
            top_dirs[d] += 1

    total_dur = sum(durations) if durations else 0.0
    avg_files = sum(files_counts) / n if n else 0.0
    avg_untracked = sum(untracked_counts) / n if n else 0.0

    patterns: list[str] = []
    dirty_like = sum(
        1
        for r in records
        if (r.get("final_status") or "") in ("dirty_uncommitted", "dirty_checkpointed")
    )
    if n >= 3 and dirty_like >= max(2, int(0.5 * n)):
        patterns.append("You often end sessions with uncommitted work still in the tree.")

    if n >= 2 and tests_skip >= max(2, int(0.6 * n)):
        patterns.append("Tests were skipped or not configured in most of these sessions.")

    if n >= 2 and drift_sessions >= 2:
        patterns.append(
            f"Scope drift (files outside the declared area) appeared in {drift_sessions} of the last {n} sessions."
        )

    if top_dirs:
        common = [d for d, _ in top_dirs.most_common(5)]
        if len(common) <= 4:
            patterns.append(f"Most edits clustered under: {', '.join(common)}.")

    if n >= 3 and wip_endings >= max(2, int(0.4 * n)):
        patterns.append(
            "WIP-style parking (stash/WIP commit) was common; consider a single clean commit when tests pass."
        )

    if prim_recs:
        top_p, _c = prim_recs.most_common(1)[0]
        patterns.append(f"Most common primary recommendation: {top_p}.")

    return {
        "session_count": n,
        "period_days": days,
        "total_duration_minutes": round(total_dur, 2),
        "average_files_changed": round(avg_files, 2),
        "average_untracked_files": round(avg_untracked, 2),
        "tests_run_count": tests_run,
        "tests_pass_count": tests_pass,
        "tests_fail_count": tests_fail,
        "tests_skipped_or_not_run": tests_skip,
        "status_breakdown": dict(status_counts),
        "sessions_with_scope_drift": drift_sessions,
        "wip_like_endings": wip_endings,
        "clean_leave_endings": clean_endings,
        "most_common_suggested_next_action": next_actions.most_common(1)[0][0] if next_actions else None,
        "most_common_top_level_dirs": [d for d, _ in top_dirs.most_common(8)],
        "most_common_primary_recommendation": prim_recs.most_common(1)[0][0] if prim_recs else None,
        "patterns_noticed": patterns,
        "sessions": [r.get("session", {}).get("session_id") or r.get("session_id") for r in records],
    }


def write_review_receipt(repo_root: Path, cfg_receipt: str | None, payload: dict[str, Any]) -> Path:
    rdir = receipt_dir(repo_root, cfg_receipt)
    rdir.mkdir(parents=True, exist_ok=True)
    ts = utc_now_iso().replace(":", "").replace("+00:00", "")[:20]
    path = rdir / f"review-{ts}.json"
    atomic_write_json(path, payload)
    return path
