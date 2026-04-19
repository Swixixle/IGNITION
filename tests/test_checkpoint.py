"""Tests for ignition checkpoint."""

from __future__ import annotations

from typer.testing import CliRunner

from ignition.cli import app


def test_checkpoint_captures_diff_stat(git_repo):
    r0 = CliRunner().invoke(
        app,
        ["start", "--task", "t", "--branch", "feat/t", "--scope", ".", "--done", "d"],
    )
    assert r0.exit_code == 0, r0.output
    (git_repo / "x.py").write_text("print(1)\n", encoding="utf-8")
    r = CliRunner().invoke(
        app,
        ["checkpoint", "--action", "note", "--note", "wip", "--no-test"],
    )
    assert r.exit_code == 0, r.output
    sess = git_repo / "ignition_data" / "sessions"
    session_files = [f for f in sess.glob("*.json") if f.name != "current_session.json"]
    import json

    data = json.loads(session_files[0].read_text(encoding="utf-8"))
    assert data["checkpoints"]
    cp = data["checkpoints"][0]
    assert "x.py" in cp["changed_files"]
    assert "x.py" in cp["diff_stat"] or "Untracked" in cp["diff_stat"]
