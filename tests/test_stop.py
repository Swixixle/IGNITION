"""Tests for ignition stop."""

from __future__ import annotations

from typer.testing import CliRunner

from ignition.cli import app


def test_stop_writes_receipt(git_repo):
    assert CliRunner().invoke(
        app,
        ["start", "--task", "t", "--branch", "feat/t", "--scope", ".", "--done", "d"],
    ).exit_code == 0
    r = CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    assert r.exit_code == 0, r.output
    rec = git_repo / "ignition_data" / "receipts"
    md = next(rec.glob("*.md"))
    js = next(rec.glob("*.json"))
    assert md.read_text(encoding="utf-8").startswith("# IGNITION")
    assert "final_status" in js.read_text(encoding="utf-8").lower() or "clean" in md.read_text(
        encoding="utf-8"
    ).lower()


def test_stop_suggested_cleanup_commands(git_repo):
    assert CliRunner().invoke(
        app,
        ["start", "--task", "t", "--branch", "feat/t", "--scope", ".", "--done", "d"],
    ).exit_code == 0
    (git_repo / "z.txt").write_text("edit", encoding="utf-8")
    r = CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    assert r.exit_code == 0, r.output
    assert "git" in r.output.lower()
