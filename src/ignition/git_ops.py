"""Narrow subprocess wrappers around Git — testable and explicit."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(
    repo_root: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=check,
        )
    except OSError as e:
        raise GitError(f"git failed to run: {e}") from e


def find_git_root(start: Path | None = None) -> Path | None:
    p = (start or Path.cwd()).resolve()
    for candidate in [p, *p.parents]:
        git_entry = candidate / ".git"
        if git_entry.exists():
            return candidate
    return None


def git_dir_abs(repo_root: Path) -> Path:
    cp = _run(repo_root, ["rev-parse", "--path-format=absolute", "--git-dir"])
    return Path(cp.stdout.strip()).resolve()


def is_linked_worktree(repo_root: Path) -> bool:
    """True if this directory is a linked worktree (.git is a file, not a directory)."""
    git_entry = repo_root / ".git"
    return git_entry.is_file()


def worktree_label(repo_root: Path) -> str:
    if is_linked_worktree(repo_root):
        return f"linked worktree at {repo_root.resolve()}"
    return f"main working tree at {repo_root.resolve()}"


def detect_default_branch(repo_root: Path) -> str | None:
    """Best-effort default branch name (for display / metadata)."""
    for cmd in (
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        ["config", "--get", "init.defaultBranch"],
    ):
        cp = _run(repo_root, cmd, check=False)
        if cp.returncode == 0 and cp.stdout.strip():
            ref = cp.stdout.strip()
            if "/" in ref:
                return ref.split("/")[-1]
            return ref
    for guess in ("main", "master"):
        if branch_exists(repo_root, guess):
            return guess
    return None


def git_user_identity(repo_root: Path) -> tuple[str | None, str | None]:
    n = _run(repo_root, ["config", "user.name"], check=False)
    e = _run(repo_root, ["config", "user.email"], check=False)
    name = n.stdout.strip() if n.returncode == 0 else None
    email = e.stdout.strip() if e.returncode == 0 else None
    return (name or None, email or None)


def get_current_branch(repo_root: Path) -> str:
    cp = _run(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    return cp.stdout.strip()


def get_current_branch_safe(repo_root: Path) -> str:
    """Like get_current_branch, but never raises (empty repo / detached edge cases)."""
    cp = _run(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    if cp.returncode != 0:
        return "(unknown)"
    out = cp.stdout.strip()
    return out if out else "(unknown)"


def head_hash(repo_root: Path) -> str:
    cp = _run(repo_root, ["rev-parse", "HEAD"])
    return cp.stdout.strip()


def status_porcelain(repo_root: Path) -> str:
    cp = _run(repo_root, ["status", "--porcelain=v1"])
    return cp.stdout


def is_working_tree_clean(repo_root: Path) -> bool:
    return status_porcelain(repo_root).strip() == ""


def diff_stat(repo_root: Path, ref: str | None = None) -> str:
    if ref:
        cp = _run(repo_root, ["diff", "--stat", ref])
    else:
        cp = _run(repo_root, ["diff", "--stat"])
    out = cp.stdout.rstrip()
    untracked = untracked_files(repo_root)
    if untracked:
        lines = "\n".join(f" {u} | untracked" for u in untracked)
        extra = f"\nUntracked files:\n{lines}"
        out = (out + extra).strip()
    return out + ("\n" if out else "")


def diff_stat_range(repo_root: Path, old_ref: str, new_ref: str = "HEAD") -> str:
    cp = _run(repo_root, ["diff", "--stat", old_ref, new_ref])
    return cp.stdout


def untracked_files(repo_root: Path) -> list[str]:
    cp = _run(repo_root, ["ls-files", "--others", "--exclude-standard"])
    return sorted({ln.strip() for ln in cp.stdout.splitlines() if ln.strip()})


def changed_files(repo_root: Path, include_untracked: bool = True) -> list[str]:
    names: list[str] = []
    cp = _run(repo_root, ["diff", "--name-only", "HEAD"])
    for line in cp.stdout.splitlines():
        line = line.strip()
        if line:
            names.append(line)
    if include_untracked:
        for u in untracked_files(repo_root):
            if u not in names:
                names.append(u)
    return sorted(set(names))


def recent_commits(repo_root: Path, n: int = 15) -> str:
    cp = _run(
        repo_root,
        ["log", f"-{n}", "--oneline", "--decorate"],
    )
    return cp.stdout.strip()


def commits_since(repo_root: Path, since_ref: str) -> list[str]:
    """One line per commit after since_ref (exclusive) up to HEAD."""
    cp = _run(repo_root, ["log", f"{since_ref}..HEAD", "--oneline"])
    lines = [ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]
    return lines


def commits_since_detailed(repo_root: Path, since_ref: str) -> list[dict[str, str]]:
    """Commits after since_ref with hash and subject."""
    cp = _run(
        repo_root,
        ["log", f"{since_ref}..HEAD", "--format=%H%x09%s"],
    )
    rows: list[dict[str, str]] = []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            h, subj = line.split("\t", 1)
            rows.append({"hash": h, "short": h[:12], "message": subj})
    return rows


def diff_numstat_against_ref(repo_root: Path, old_ref: str) -> tuple[int, int, int]:
    """Return (insertions, deletions, files_changed) vs old_ref for tracked diffs."""
    cp = _run(repo_root, ["diff", "--numstat", old_ref, "HEAD"], check=False)
    ins = dels = files = 0
    for line in cp.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0] != "-":
            try:
                ins += int(parts[0])
                dels += int(parts[1])
                files += 1
            except ValueError:
                continue
    return ins, dels, files


def porcelain_summary(repo_root: Path) -> dict[str, int]:
    """Rough counts from porcelain lines (M/A/D/?)."""
    lines = [ln for ln in status_porcelain(repo_root).splitlines() if ln.strip()]
    added = modified = deleted = untracked = 0
    for ln in lines:
        idx = ln[:2] if len(ln) >= 2 else ln
        if idx.startswith("??"):
            untracked += 1
        elif "A" in idx or idx.startswith("A"):
            added += 1
        elif "D" in idx:
            deleted += 1
        elif "M" in idx or "R" in idx:
            modified += 1
    return {
        "lines": len(lines),
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "untracked": untracked,
    }


def create_branch(repo_root: Path, branch: str, start_point: str | None = None) -> None:
    args = ["checkout", "-b", branch]
    if start_point:
        args.append(start_point)
    cp = _run(repo_root, args, check=False)
    if cp.returncode != 0:
        raise GitError(cp.stderr.strip() or cp.stdout.strip() or "branch creation failed")


def switch_branch(repo_root: Path, branch: str) -> None:
    cp = _run(repo_root, ["checkout", branch], check=False)
    if cp.returncode != 0:
        raise GitError(cp.stderr.strip() or cp.stdout.strip() or "checkout failed")


def branch_exists(repo_root: Path, branch: str) -> bool:
    cp = _run(repo_root, ["rev-parse", "--verify", branch], check=False)
    return cp.returncode == 0


def switch_or_create_branch(repo_root: Path, branch: str) -> None:
    if branch_exists(repo_root, branch):
        switch_branch(repo_root, branch)
    else:
        create_branch(repo_root, branch)


def stash_push(repo_root: Path, message: str) -> None:
    cp = _run(
        repo_root,
        ["stash", "push", "-u", "-m", message],
        check=False,
    )
    if cp.returncode != 0:
        raise GitError(cp.stderr.strip() or "stash failed")


def stash_list(repo_root: Path) -> str:
    cp = _run(repo_root, ["stash", "list"])
    return cp.stdout.strip()


def commit_all(repo_root: Path, message: str) -> str:
    _run(repo_root, ["add", "-A"])
    cp = _run(repo_root, ["commit", "-m", message], check=False)
    if cp.returncode != 0:
        raise GitError(cp.stderr.strip() or cp.stdout.strip() or "commit failed")
    return head_hash(repo_root)


def init_repo(path: Path) -> None:
    cp = _run(path, ["init"], check=False)
    if cp.returncode != 0:
        raise GitError("git init failed")
