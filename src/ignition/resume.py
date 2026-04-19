"""Resume an unfinished session."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ignition import git_ops
from ignition import session as session_mod
from ignition.utils import utc_now_iso


@dataclass
class ResumeResult:
    session_path: Path
    data: dict[str, Any]
    branch_warning: str | None
    head_warning: str | None


def unfinished_on_branch(
    repo_root: Path,
    session_rel: str | None,
    branch: str,
) -> tuple[Path, dict[str, Any]] | tuple[None, None]:
    """Latest unfinished session for this repo that matches the given branch."""
    for path, data in _unfinished_candidates(repo_root, session_rel):
        if data.get("branch") == branch:
            return path, data
    return None, None


def _unfinished_candidates(repo_root: Path, session_rel: str | None) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    rr = str(repo_root.resolve())
    for path in session_mod.iter_session_json_paths(repo_root, session_rel):
        data = session_mod.load_session_soft(path)
        if data is None:
            continue
        if data.get("repo_root") and data["repo_root"] != rr:
            continue
        if session_mod.is_session_unfinished(data):
            out.append((path, data))
    out.sort(key=lambda x: x[1].get("started_at", ""), reverse=True)
    return out


def find_resume_target(
    repo_root: Path,
    session_rel: str | None,
    *,
    session_id: str | None,
    latest: bool = True,
) -> tuple[Path, dict[str, Any]] | tuple[None, None]:
    if session_id:
        path = session_mod.session_file_path(repo_root, session_rel, session_id)
        if not path.is_file():
            return None, None
        data = session_mod.load_session_soft(path)
        if data is None or not session_mod.is_session_unfinished(data):
            return None, None
        return path, data

    cands = _unfinished_candidates(repo_root, session_rel)
    if not cands:
        return None, None
    return cands[0] if latest else cands[-1]


def warnings_for_resume(repo_root: Path, data: dict[str, Any]) -> tuple[str | None, str | None]:
    branch_w: str | None = None
    head_w: str | None = None
    recorded = data.get("branch")
    current = git_ops.get_current_branch(repo_root)
    if recorded and recorded != current:
        branch_w = f"Session recorded branch `{recorded}` but you are on `{current}`."
    checkpoints = data.get("checkpoints") or []
    last_h = None
    for cp in reversed(checkpoints):
        if cp.get("head_hash"):
            last_h = cp["head_hash"]
            break
    if last_h:
        now = git_ops.head_hash(repo_root)
        if now != last_h:
            head_w = (
                f"HEAD is `{now[:12]}`; last checkpoint recorded `{last_h[:12]}`. "
                "History may have moved."
            )
    return branch_w, head_w


def apply_resume(
    repo_root: Path,
    session_rel: str | None,
    path: Path,
    data: dict[str, Any],
) -> ResumeResult:
    session_mod.write_active_pointer(repo_root, session_rel, path, data["session_id"])
    session_mod.merge_session_update(
        path,
        {
            "last_resumed_at": utc_now_iso(),
        },
    )
    fresh = session_mod.load_session(path)
    b, h = warnings_for_resume(repo_root, fresh)
    return ResumeResult(session_path=path, data=fresh, branch_warning=b, head_warning=h)
