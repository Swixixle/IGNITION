"""v5: init, frictionless start, current, close-stale, hooks, guardrails, heartbeats."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from ignition.cli import app
from ignition.config import load_config
from ignition import git_ops
from ignition import session as session_mod


def test_init_creates_config_and_dirs(git_repo: Path):
    r = CliRunner().invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    assert (git_repo / "ignition.toml").is_file()
    assert (git_repo / "ignition_data" / "sessions").is_dir()
    assert (git_repo / "ignition_data" / "receipts").is_dir()


def test_start_yes_infers_branch_and_scope(git_repo: Path):
    (git_repo / "src").mkdir()
    (git_repo / "src" / "a.py").write_text("1", encoding="utf-8")
    subprocess.run(["git", "add", "src/a.py"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add src"], cwd=git_repo, check=True, capture_output=True)

    r = CliRunner().invoke(
        app,
        ["start", "--yes", "--task", "hello feature", "--print-assumptions"],
    )
    assert r.exit_code == 0, r.output
    assert "Assumption:" in r.output
    cfg = load_config(git_repo)
    cur = git_ops.get_current_branch(git_repo)
    assert cur.startswith(cfg.default_feature_branch_prefix)


def test_start_duplicate_blocked_without_force(git_repo: Path):
    r1 = CliRunner().invoke(
        app,
        ["start", "--yes", "--task", "first", "--no-branch-switch"],
    )
    assert r1.exit_code == 0, r1.output
    r2 = CliRunner().invoke(
        app,
        ["start", "--yes", "--task", "second", "--no-branch-switch"],
    )
    assert r2.exit_code == 1
    assert "active session" in r2.output.lower() or "already exists" in r2.output.lower()


def test_start_force_after_duplicate(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "a", "--no-branch-switch"])
    r = CliRunner().invoke(
        app,
        ["start", "--yes", "--task", "b", "--no-branch-switch", "--force"],
    )
    assert r.exit_code == 0, r.output


def test_current_json_active_and_inactive(git_repo: Path):
    r0 = CliRunner().invoke(app, ["current", "--json"])
    assert r0.exit_code == 0
    d0 = json.loads(r0.output.strip())
    assert d0.get("active") is False

    CliRunner().invoke(app, ["start", "--yes", "--task", "c", "--no-branch-switch"])
    r1 = CliRunner().invoke(app, ["current", "--json"])
    d1 = json.loads(r1.output.strip())
    assert d1.get("active") is True
    assert d1.get("task") == "c"
    assert d1.get("schema_version") is not None
    assert d1.get("tool_version") is not None


def test_close_stale_dry_run(git_repo: Path, monkeypatch):
    monkeypatch.chdir(git_repo)
    cfg = load_config(git_repo)
    sdir = git_repo / cfg.session_dir
    sdir.mkdir(parents=True, exist_ok=True)
    old = datetime.now(timezone.utc) - timedelta(days=100)
    sid = "old-stale-session"
    payload = {
        "session_id": sid,
        "repo_root": str(git_repo.resolve()),
        "branch": "main",
        "task": "ghost",
        "scope": [],
        "definition_of_done": "",
        "started_at": old.replace(microsecond=0).isoformat(),
        "initial_git_status": "",
        "initial_head": "abc",
        "status": "active",
        "checkpoints": [],
    }
    (sdir / f"{sid}.json").write_text(json.dumps(payload), encoding="utf-8")

    r = CliRunner().invoke(app, ["close-stale", "--days", "30", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert sid in r.output


def test_hook_print_zsh():
    r = CliRunner().invoke(app, ["hook", "print", "--shell", "zsh"])
    assert r.exit_code == 0
    assert "alias igs=" in r.output
    assert "ignition current" in r.output


def test_project_preferred_scope_in_config(git_repo: Path):
    (git_repo / "ignition.toml").write_text(
        '[project]\npreferred_scope = ["src/", "tests/"]\n',
        encoding="utf-8",
    )
    cfg = load_config(git_repo)
    assert cfg.preferred_scope == ["src/", "tests/"]


def test_status_sets_last_status_at(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "t", "--no-branch-switch"])
    CliRunner().invoke(app, ["status"])
    cfg = load_config(git_repo)
    for p in session_mod.iter_session_json_paths(git_repo, cfg.session_dir):
        data = session_mod.load_session(p)
        if data.get("task") == "t":
            assert data.get("last_status_at")
            break
    else:
        raise AssertionError("session not found")
