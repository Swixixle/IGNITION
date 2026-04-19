"""Branch/session hygiene hints — informational only, no Git network or sync."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ignition import session as session_mod


def count_sessions_on_branch(
    repo_root: Path,
    cfg_session: str | None,
    branch: str,
) -> int:
    rr = str(repo_root.resolve())
    n = 0
    for path in session_mod.iter_session_json_paths(repo_root, cfg_session):
        data = session_mod.load_session_soft(path)
        if data is None:
            continue
        if data.get("repo_root") != rr:
            continue
        if data.get("branch") != branch:
            continue
        n += 1
    return n


def count_clean_complete_stops_on_branch(
    repo_root: Path,
    cfg_session: str | None,
    branch: str,
) -> int:
    rr = str(repo_root.resolve())
    n = 0
    for path in session_mod.iter_session_json_paths(repo_root, cfg_session):
        data = session_mod.load_session_soft(path)
        if data is None:
            continue
        if data.get("repo_root") != rr:
            continue
        if data.get("branch") != branch:
            continue
        if data.get("final_status") == "clean_complete":
            n += 1
    return n


def branch_hygiene_hints(
    repo_root: Path,
    cfg_session: str | None,
    *,
    branch: str,
    default_branch: str,
    session_data: dict[str, Any] | None,
) -> list[str]:
    hints: list[str] = []
    sess_on_br = count_sessions_on_branch(repo_root, cfg_session, branch)
    clean_stops = count_clean_complete_stops_on_branch(repo_root, cfg_session, branch)

    if branch != default_branch and sess_on_br >= 4:
        hints.append(f"This branch has recorded activity across {sess_on_br} sessions — consider merging or rebasing soon.")

    if branch != default_branch and sess_on_br >= 2 and clean_stops == 0:
        hints.append("You have not had a clean_complete stop on this branch yet; consider cleaning up before continuing.")

    if session_data and session_data.get("started_at") and not session_data.get("checkpoints"):
        hints.append("Long session without checkpoints — consider a checkpoint before large changes.")

    return hints


def sessions_on_branch_for_receipt(
    repo_root: Path,
    cfg_session: str | None,
    branch: str,
) -> int:
    return count_sessions_on_branch(repo_root, cfg_session, branch)
