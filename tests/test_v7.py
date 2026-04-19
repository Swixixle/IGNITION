"""v7: begin, next, amend-context, checklist, carry-forward on stop."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ignition.cli import app
from ignition import carryforward as cf_mod
from ignition.config import load_config
from ignition import session as session_mod


def test_begin_suggests_resume_when_unfinished_on_branch(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "u", "--no-branch-switch"])
    r = CliRunner().invoke(app, ["begin", "--yes", "--task", "other", "--no-branch-switch"])
    assert r.exit_code == 1
    assert "resume" in r.output.lower() or "unfinished" in r.output.lower()


def test_begin_with_force_starts(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "u2", "--no-branch-switch"])
    r = CliRunner().invoke(
        app,
        ["begin", "--force", "--yes", "--task", "new", "--no-branch-switch"],
    )
    assert r.exit_code == 0, r.output


def test_carryforward_on_stop(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "cf", "--no-branch-switch"])
    CliRunner().invoke(
        app,
        ["amend-context", "--todo", "finish tests", "--risk", "flake"],
    )
    CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    cfg = load_config(git_repo)
    for p in session_mod.iter_session_json_paths(git_repo, cfg.session_dir):
        d = session_mod.load_session(p)
        if d.get("task") == "cf" and d.get("status") == "stopped":
            assert d.get("carryforward_todos") or d.get("carryforward_summary")
            break
    else:
        raise AssertionError("stopped session not found")


def test_next_shows_prior(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "n1", "--no-branch-switch"])
    CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    r = CliRunner().invoke(app, ["next"])
    assert r.exit_code == 0
    assert "n1" in r.output or "Last session" in r.output


def test_amend_context_updates(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "am", "--no-branch-switch"])
    r = CliRunner().invoke(app, ["amend-context", "--task", "amended", "--todo", "x"])
    assert r.exit_code == 0, r.output
    cfg = load_config(git_repo)
    sp = session_mod.read_active_session_file(git_repo, cfg.session_dir)
    assert sp
    d = session_mod.load_session(sp)
    assert d.get("task") == "amended"
    assert "x" in (d.get("carryforward_todos") or [])


def test_checklist_reads_config(git_repo: Path):
    (git_repo / "ignition.toml").write_text(
        '[project]\nmerge_checklist = ["tests pass", "lint"]\nreview_command = "pytest -q"\n',
        encoding="utf-8",
    )
    r = CliRunner().invoke(app, ["checklist"])
    assert r.exit_code == 0
    assert "tests pass" in r.output
    assert "pytest" in r.output


def test_checklist_soft_empty(git_repo: Path):
    (git_repo / "ignition.toml").write_text("default_branch = \"main\"\n", encoding="utf-8")
    r = CliRunner().invoke(app, ["checklist"])
    assert r.exit_code == 0
    assert "merge_checklist" in r.output.lower() or "No" in r.output


def test_build_next_payload_json(git_repo: Path):
    cfg = load_config(git_repo)
    p = cf_mod.build_next_payload(git_repo, cfg, branch="main")
    assert "repo" in p
