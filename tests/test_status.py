"""Tests for ignition status."""

from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from ignition.cli import app


def test_status_reports_changed_files(git_repo):
    assert CliRunner().invoke(
        app,
        ["start", "--task", "t", "--branch", "feat/t", "--scope", ".", "--done", "d"],
    ).exit_code == 0
    (git_repo / "n.py").write_text("1", encoding="utf-8")
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 0
    assert "Changed:" in r.output
    assert "1 file" in r.output or "file(s)" in r.output


def test_scope_drift_warning(git_repo):
    (git_repo / "ignition.toml").write_text(
        "warn_on_scope_drift = true\nmax_files_before_warning = 1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "ignition.toml"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "cfg"], cwd=git_repo, check=True)
    assert CliRunner().invoke(
        app,
        [
            "start",
            "--task",
            "t",
            "--branch",
            "feat/t",
            "--scope",
            "only_here.txt",
            "--done",
            "d",
        ],
    ).exit_code == 0
    (git_repo / "only_here.txt").write_text("ok", encoding="utf-8")
    (git_repo / "other.py").write_text("no", encoding="utf-8")
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 0
    assert "outside" in r.output.lower() or "scope" in r.output.lower()
