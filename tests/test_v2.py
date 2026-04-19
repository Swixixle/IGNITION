"""v2 features: resume, list, doctor, receipts, scope summaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ignition.cli import app


def test_resume_rebinds_latest_unfinished(git_repo):
    assert (
        CliRunner().invoke(
            app,
            ["start", "--task", "resume-me", "--branch", "feat/r", "--scope", ".", "--done", "d"],
        ).exit_code
        == 0
    )
    ptr = git_repo / "ignition_data" / "sessions" / "current_session.json"
    assert ptr.is_file()
    ptr.unlink()
    r = CliRunner().invoke(app, ["resume", "--latest"])
    assert r.exit_code == 0, r.output
    assert "resume-me" in r.output
    assert ptr.is_file()


def test_list_json(git_repo):
    assert (
        CliRunner().invoke(
            app,
            ["start", "--task", "l", "--branch", "feat/l", "--scope", ".", "--done", "d"],
        ).exit_code
        == 0
    )
    r = CliRunner().invoke(app, ["list", "--json", "--limit", "5"])
    assert r.exit_code == 0
    doc = json.loads(r.output)
    rows = doc.get("sessions", doc)
    assert isinstance(rows, list)
    assert rows[0]["session_id"]
    assert "branch" in rows[0]


def test_doctor_inside_repo(git_repo):
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code == 0
    assert "pass" in r.output.lower() or "PASS" in r.output


def test_doctor_outside_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["doctor"])
    assert r.exit_code != 0


def test_doctor_stale_pointer(git_repo):
    CliRunner().invoke(
        app,
        ["start", "--task", "x", "--branch", "feat/x", "--scope", ".", "--done", "d"],
    )
    ptr = git_repo / "ignition_data/sessions/current_session.json"
    ptr.write_text(
        json.dumps({"session_file": str(git_repo / "nonexistent.json"), "repo_root": str(git_repo.resolve())}),
        encoding="utf-8",
    )
    r = CliRunner().invoke(app, ["doctor"])
    assert "missing" in r.output.lower() or "stale" in r.output.lower() or "warn" in r.output.lower()


def test_stop_receipt_has_commits_detailed(git_repo):
    CliRunner().invoke(
        app,
        ["start", "--task", "t", "--branch", "feat/t", "--scope", ".", "--done", "d"],
    )
    (git_repo / "f.py").write_text("1", encoding="utf-8")
    CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    js = next((git_repo / "ignition_data/receipts").glob("*.json"))
    data = json.loads(js.read_text(encoding="utf-8"))
    assert "commits_detailed" in data
    assert "file_stats" in data
    assert "parking_recommendations" in data


def test_status_scope_in_out(git_repo):
    CliRunner().invoke(
        app,
        ["start", "--task", "s", "--branch", "feat/s", "--scope", "in.txt", "--done", "d"],
    )
    (git_repo / "in.txt").write_text("a", encoding="utf-8")
    (git_repo / "out.txt").write_text("b", encoding="utf-8")
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 0
    assert "In scope:" in r.output or "Out of scope:" in r.output


def test_stop_suggests_git_when_dirty(git_repo):
    CliRunner().invoke(
        app,
        ["start", "--task", "d", "--branch", "feat/d", "--scope", ".", "--done", "d"],
    )
    (git_repo / "dirty.txt").write_text("x", encoding="utf-8")
    r = CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    assert r.exit_code == 0
    assert "git" in r.output.lower()
