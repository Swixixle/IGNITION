"""Time-bucketed trend metrics from session receipts — numbers only, no charts in v4."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ignition.normalize import normalize_record
from ignition.atomic_io import atomic_write_json
from ignition.paths import receipt_dir
from ignition.review import filter_by_days, iter_session_records
from ignition.utils import utc_now_iso


def _week_key(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def build_trends(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    *,
    days: int = 30,
    all_repos: bool = False,
) -> dict[str, Any]:
    records = iter_session_records(repo_root, cfg_session, cfg_receipt, all_repos=all_repos)
    records = filter_by_days(records, days)
    n = len(records)
    if n == 0:
        return {
            "period_days": days,
            "session_count": 0,
            "sessions_per_week": 0.0,
            "averages": {},
            "rates": {},
            "weekly_buckets": {},
            "observations": [],
        }

    weeks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    durations: list[float] = []
    files_list: list[int] = []
    commit_counts: list[int] = []
    checkpoint_counts: list[int] = []
    clean_n = drift_n = fail_n = dirty_n = 0

    for raw in records:
        r = normalize_record(raw)
        sess = r.get("session") or {}
        st = sess.get("started_at")
        dt = None
        if st:
            try:
                dt = datetime.fromisoformat(st.replace("Z", "+00:00"))
            except ValueError:
                pass
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            weeks[_week_key(dt)].append(r)

        en = sess.get("ended_at")
        if st and en:
            try:
                d0 = datetime.fromisoformat(st.replace("Z", "+00:00"))
                d1 = datetime.fromisoformat(en.replace("Z", "+00:00"))
                durations.append((d1 - d0).total_seconds() / 60.0)
            except ValueError:
                pass

        files_list.append(int(r.get("files_changed_count") or 0))
        commit_counts.append(len(r.get("commits_during_session") or []))
        checkpoint_counts.append(int(r.get("checkpoints_count") or 0))

        fs = r.get("final_status") or ""
        if fs in ("clean_complete", "clean_in_progress"):
            clean_n += 1
        if fs == "blocked_by_failing_tests":
            fail_n += 1
        if fs in ("dirty_uncommitted", "dirty_checkpointed"):
            dirty_n += 1
        if r.get("scope_drift_warning") or (r.get("scope_drift_count") or 0) > 0:
            drift_n += 1

    span_weeks = max(days / 7.0, 0.1)

    observations: list[str] = []
    if n >= 2 and durations:
        avg_dur = sum(durations) / len(durations)
        observations.append(f"Average session length in this window: about {avg_dur:.0f} minutes.")
    if n >= 2 and drift_n >= max(2, n // 2):
        observations.append("Scope drift appears in a large share of these sessions.")

    return {
        "period_days": days,
        "session_count": n,
        "sessions_per_week": round(n / span_weeks, 2),
        "averages": {
            "duration_minutes": round(sum(durations) / len(durations), 2) if durations else None,
            "files_changed": round(sum(files_list) / n, 2),
            "commits_per_session": round(sum(commit_counts) / n, 2),
            "checkpoints_per_session": round(sum(checkpoint_counts) / n, 2),
        },
        "rates": {
            "clean_complete_or_in_progress": round(clean_n / n, 3),
            "dirty_uncommitted_like": round(dirty_n / n, 3),
            "blocked_by_failing_tests": round(fail_n / n, 3),
            "scope_drift_frequency": round(drift_n / n, 3),
        },
        "weekly_buckets": {k: len(v) for k, v in sorted(weeks.items())},
        "observations": observations,
    }


def write_trends_receipt(repo_root: Path, cfg_receipt: str | None, payload: dict[str, Any]) -> Path:
    rdir = Path(receipt_dir(repo_root, cfg_receipt))
    rdir.mkdir(parents=True, exist_ok=True)
    ts = utc_now_iso().replace(":", "").replace("+00:00", "")[:20]
    path = rdir / f"trends-{ts}.json"
    atomic_write_json(path, payload)
    return path
