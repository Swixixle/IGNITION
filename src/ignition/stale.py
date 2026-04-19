"""Close abandoned sessions that were never stopped (mark only; no deletion)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ignition.atomic_io import atomic_write_json
from ignition import session as session_mod
from ignition.paths import receipt_dir
from ignition.utils import utc_now_iso


def _parse_started(data: dict[str, Any]) -> datetime | None:
    s = data.get("started_at")
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class StaleCandidate:
    path: Path
    session_id: str
    started_at: str


def find_stale_sessions(
    repo_root: Path,
    session_rel: str | None,
    *,
    older_than_days: int,
) -> list[StaleCandidate]:
    rr = str(repo_root.resolve())
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    out: list[StaleCandidate] = []
    for path in session_mod.iter_session_json_paths(repo_root, session_rel):
        data = session_mod.load_session_soft(path)
        if data is None:
            continue
        if data.get("repo_root") and data["repo_root"] != rr:
            continue
        if not session_mod.is_session_unfinished(data):
            continue
        st = _parse_started(data)
        if st is None:
            continue
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        if st >= cutoff:
            continue
        out.append(
            StaleCandidate(
                path=path,
                session_id=data.get("session_id", path.stem),
                started_at=data.get("started_at", ""),
            )
        )
    return out


def close_stale_session(
    repo_root: Path,
    cfg_session: str | None,
    cfg_receipt: str | None,
    path: Path,
    *,
    reason: str,
) -> Path:
    """Mark session stale_closed; write receipt; return receipt path."""
    now = utc_now_iso()
    data = session_mod.load_session(path)
    sid = data.get("session_id", path.stem)
    session_mod.merge_session_update(
        path,
        {
            "status": "stale_closed",
            "stopped_at": now,
            "stale_closed_at": now,
            "stale_reason": reason,
            "final_status": "stale_closed",
        },
    )
    rdir = receipt_dir(repo_root, cfg_receipt)
    rdir.mkdir(parents=True, exist_ok=True)
    safe = now.replace(":", "").replace("+00:00", "Z")[:20]
    receipt_path = rdir / f"stale-closed-{sid}-{safe}.json"
    payload = {
        "kind": "stale_closed",
        "generated_at": now,
        "session_id": sid,
        "session_file": str(path.resolve()),
        "reason": reason,
    }
    atomic_write_json(receipt_path, payload)
    return receipt_path


def clear_pointer_if_points_to(repo_root: Path, cfg_session: str | None, session_path: Path) -> bool:
    raw = session_mod.read_active_pointer_raw(repo_root, cfg_session)
    if not raw:
        return False
    sf = raw.get("session_file", "")
    if not sf:
        return False
    if Path(sf).resolve() == session_path.resolve():
        session_mod.clear_active_pointer(repo_root, cfg_session)
        return True
    return False
