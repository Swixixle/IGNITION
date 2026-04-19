"""Tests for ignition start."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ignition.cli import app


def test_start_refuses_outside_git_repo(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["start", "--task", "x", "--branch", "f", "--no-branch-switch"])
    assert r.exit_code == 1
    assert "not inside a Git repository" in r.output


def test_start_creates_session_record(git_repo):
    r = CliRunner().invoke(
        app,
        [
            "start",
            "--task",
            "my task",
            "--branch",
            "feat/my-task",
            "--scope",
            "src/foo.py,tests/",
            "--done",
            "tests pass",
        ],
    )
    assert r.exit_code == 0, r.output
    sess_dir = git_repo / "ignition_data" / "sessions"
    files = list(sess_dir.glob("*.json"))
    assert len(files) >= 2
    session_files = [f for f in files if f.name != "current_session.json"]
    data = json.loads(session_files[0].read_text(encoding="utf-8"))
    assert data["task"] == "my task"
    assert data["branch"] == "feat/my-task"
    assert "src/foo.py" in data["scope"]
    assert data["definition_of_done"] == "tests pass"
    assert data["status"] == "active"


def test_dirty_main_warning_invoked(git_repo, monkeypatch):
    (git_repo / "dirty.txt").write_text("d", encoding="utf-8")
    monkeypatch.setattr(
        "ignition.prompts.prompt_dirty_resolution",
        lambda: "abort",
    )
    r = CliRunner().invoke(
        app,
        ["start", "--task", "t", "--branch", "feat/x", "--no-branch-switch"],
    )
    assert r.exit_code == 1
    assert "uncommitted" in r.output.lower() or "Warning" in r.output
