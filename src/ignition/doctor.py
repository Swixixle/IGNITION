"""Environment and repo checks — practical, not preachy."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ignition import git_ops
from ignition.config import effective_status_test_command, load_config
from ignition import schema as schema_mod
from ignition import session as session_mod
from ignition.paths import ACTIVE_SESSION_FILE, active_session_path, session_dir


@dataclass
class Check:
    name: str
    level: str  # pass | warn | fail
    detail: str
    fix: str | None = None


def run_doctor(repo_root: Path | None) -> list[Check]:
    results: list[Check] = []
    if repo_root is None:
        results.append(
            Check(
                "git repository",
                "fail",
                "Not inside a Git repository.",
                "cd into a clone or run git init.",
            )
        )
        return results

    cfg = load_config(repo_root)

    results.append(Check("git repository", "pass", f"Root: {repo_root.resolve()}"))

    branch = git_ops.get_current_branch(repo_root)
    results.append(Check("current branch", "pass", f"`{branch}`"))

    default_b = cfg.default_branch
    porcelain = git_ops.status_porcelain(repo_root)
    dirty = bool(porcelain.strip())
    if branch == default_b and dirty:
        results.append(
            Check(
                "default branch hygiene",
                "warn",
                f"On `{default_b}` with a dirty working tree.",
                f"Consider a feature branch or ignition start instead of long-lived work on {default_b}.",
            )
        )
    else:
        results.append(Check("default branch hygiene", "pass", "OK"))

    ap = active_session_path(repo_root, cfg.session_dir)
    pointer = session_mod.read_active_pointer_raw(repo_root, cfg.session_dir)
    if ap.is_file() and pointer is None:
        results.append(
            Check(
                "active session pointer",
                "warn",
                "current_session.json exists but is empty or not valid JSON.",
                "Delete it or restore a valid pointer; `ignition resume` may help after fixing session files.",
            )
        )
    elif pointer:
        sf = pointer.get("session_file", "")
        pr = pointer.get("repo_root", "")
        if pr and Path(pr).resolve() != repo_root.resolve():
            results.append(
                Check(
                    "active session pointer",
                    "warn",
                    f"Pointer repo_root `{pr}` does not match current root.",
                    "Remove or fix ignition_data/sessions/current_session.json.",
                )
            )
        elif not sf or not Path(sf).is_file():
            results.append(
                Check(
                    "active session pointer",
                    "warn",
                    "current_session.json points to a missing session file.",
                    "Run ignition resume or delete the stale pointer.",
                )
            )
        else:
            results.append(Check("active session pointer", "pass", f"→ {sf}"))
    else:
        results.append(Check("active session pointer", "pass", "No active session (expected if idle)."))

    sdir = repo_root / cfg.session_dir
    rdir = repo_root / cfg.receipt_dir
    for label, d in (("sessions dir", sdir), ("receipts dir", rdir)):
        try:
            d.mkdir(parents=True, exist_ok=True)
            test = d / ".ignition_write_test"
            test.write_text("ok", encoding="utf-8")
            test.unlink()
            results.append(Check(f"{label} writable", "pass", str(d)))
        except OSError as e:
            results.append(
                Check(
                    f"{label} writable",
                    "fail",
                    str(e),
                    "Fix permissions or change session_dir / receipt_dir in ignition.toml.",
                )
            )

    test_cmd = effective_status_test_command(cfg)
    if test_cmd:
        exe = test_cmd.split()[0]
        found = shutil.which(exe) is not None
        if found:
            results.append(Check("test command on PATH", "pass", f"`{exe}`"))
        else:
            results.append(
                Check(
                    "test command on PATH",
                    "warn",
                    f"First token `{exe}` not found on PATH.",
                    "Install the tool or fix auto_*_test_command.",
                )
            )
    else:
        results.append(Check("test command", "pass", "Not configured (optional)."))

    if git_ops.is_linked_worktree(repo_root):
        results.append(
            Check(
                "worktree",
                "pass",
                git_ops.worktree_label(repo_root),
            )
        )
    else:
        results.append(Check("worktree", "pass", "Single working tree (not a linked worktree)."))

    name, email = git_ops.git_user_identity(repo_root)
    if name and email:
        results.append(Check("git identity", "pass", f"{name} <{email}>"))
    else:
        results.append(
            Check(
                "git identity",
                "warn",
                f"user.name={name!r} user.email={email!r}",
                "git config user.name / user.email for meaningful commits.",
            )
        )

    untracked = len(git_ops.untracked_files(repo_root))
    if untracked >= cfg.untracked_warning_threshold:
        results.append(
            Check(
                "untracked files",
                "warn",
                f"{untracked} untracked file(s) (threshold {cfg.untracked_warning_threshold}).",
                "Review .gitignore or add files intentionally.",
            )
        )
    else:
        results.append(Check("untracked files", "pass", f"{untracked} below threshold"))

    sdir = session_dir(repo_root, cfg.session_dir)
    if sdir.is_dir():
        by_id: dict[str, list[str]] = {}
        unreadable = 0
        forward_schema = 0
        for path in sorted(sdir.glob("*.json")):
            if path.name == ACTIVE_SESSION_FILE:
                continue
            data = session_mod.load_session_soft(path)
            if data is None:
                unreadable += 1
                continue
            sv = data.get("schema_version")
            try:
                iv = int(sv) if sv is not None else schema_mod.CURRENT_SESSION_SCHEMA_VERSION
            except (TypeError, ValueError):
                iv = schema_mod.CURRENT_SESSION_SCHEMA_VERSION
            if iv > schema_mod.CURRENT_SESSION_SCHEMA_VERSION:
                forward_schema += 1
            sid = str(data.get("session_id") or path.stem)
            by_id.setdefault(sid, []).append(str(path.name))

        if unreadable:
            results.append(
                Check(
                    "session JSON files",
                    "warn",
                    f"{unreadable} session file(s) are empty or not valid JSON.",
                    "Fix or remove broken files, or restore from export; `ignition import` can merge known-good data.",
                )
            )
        else:
            results.append(Check("session JSON files", "pass", "All session JSON files parse."))

        dupes = [k for k, v in by_id.items() if len(v) > 1]
        if dupes:
            results.append(
                Check(
                    "duplicate session_id",
                    "warn",
                    f"Same session_id appears in multiple files (example: {dupes[0]}).",
                    "Keep one canonical file per id; archive or delete duplicates after verifying contents.",
                )
            )
        else:
            results.append(Check("duplicate session_id", "pass", "No duplicate session_id values."))

        if forward_schema:
            results.append(
                Check(
                    "session schema version",
                    "warn",
                    f"{forward_schema} record(s) report a newer schema than this IGNITION understands.",
                    "Upgrade IGNITION or re-export after migration when available.",
                )
            )

    return results


def checks_to_dict(checks: list[Check]) -> list[dict[str, Any]]:
    return [{"name": c.name, "level": c.level, "detail": c.detail, "fix": c.fix} for c in checks]
