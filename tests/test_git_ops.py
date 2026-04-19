"""Tests for git_ops wrappers."""

from __future__ import annotations

import subprocess

from ignition import git_ops


def test_find_git_root(git_repo):
    root = git_ops.find_git_root(git_repo)
    assert root == git_repo.resolve()


def test_head_branch_status(git_repo):
    assert git_ops.get_current_branch(git_repo) == "main"
    h = git_ops.head_hash(git_repo)
    assert len(h) == 40
    assert git_ops.is_working_tree_clean(git_repo)


def test_changed_files_after_edit(git_repo):
    (git_repo / "a.txt").write_text("x", encoding="utf-8")
    names = git_ops.changed_files(git_repo)
    assert "a.txt" in names


def test_commits_since(git_repo):
    h0 = git_ops.head_hash(git_repo)
    (git_repo / "b.txt").write_text("y", encoding="utf-8")
    subprocess.run(["git", "add", "b.txt"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "add b"], cwd=git_repo, check=True)
    since = git_ops.commits_since(git_repo, h0)
    assert len(since) == 1
    assert "add b" in since[0]
