"""v3: recommend, snapshot, decisions on stop, commit messages, split hints, scorecard."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from ignition.cli import app
from ignition.config import load_config
from ignition.decisions import (
    build_commit_message_suggestions,
    build_decision_bundle,
    cluster_unrelated_paths,
    docs_code_tests_mix,
)


def test_commit_message_suggestions():
    c, w = build_commit_message_suggestions("Fix auth", ["src/a.py", "tests/t.py"], ["src/"])
    assert "Fix auth" in c
    assert "WIP" in w


def test_split_hint_top_level_dirs():
    paths = ["a/x", "b/y", "c/z"]
    assert cluster_unrelated_paths(paths, 3)


def test_docs_code_tests_mix():
    assert docs_code_tests_mix(["docs/x.md", "src/a.py", "tests/t.py"])


def test_recommend_writes_json_and_prints(git_repo):
    assert (
        CliRunner().invoke(
            app,
            ["start", "--task", "rec", "--branch", "feat/r", "--scope", ".", "--done", "d"],
        ).exit_code
        == 0
    )
    r = CliRunner().invoke(app, ["recommend"])
    assert r.exit_code == 0, r.output
    recs = list((git_repo / "ignition_data/receipts").glob("recommend-*.json"))
    assert recs
    data = json.loads(recs[-1].read_text(encoding="utf-8"))
    assert data.get("primary_recommendation")
    assert data.get("suggested_git_commands") is not None


def test_recommend_primary_fix_tests_when_failing(git_repo):
    CliRunner().invoke(
        app,
        ["start", "--task", "t", "--branch", "feat/t", "--scope", ".", "--done", "d"],
    )

    class TR:
        skipped = False
        exit_code = 1

    b = build_decision_bundle(
        git_repo,
        load_config(git_repo),
        {},
        TR(),
        pointer_stale=False,
    )
    assert b.primary_key == "fix_tests_first"


def test_stop_receipt_includes_decisions_v3(git_repo):
    CliRunner().invoke(
        app,
        ["start", "--task", "s", "--branch", "feat/s", "--scope", ".", "--done", "d"],
    )
    r = CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    assert r.exit_code == 0, r.output
    assert "What to do next" in r.output or "Primary:" in r.output
    js = next((git_repo / "ignition_data/receipts").glob("*.json"))
    # pick session receipt not recommend
    for p in (git_repo / "ignition_data/receipts").glob("*.json"):
        if p.name.startswith("recommend-"):
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("decisions_v3"):
            assert data["decisions_v3"]["primary_recommendation"]
            assert data.get("session_scorecard")
            break
    else:
        raise AssertionError("no decisions_v3 in receipts")


def test_snapshot_writes_file_and_session(git_repo):
    CliRunner().invoke(
        app,
        ["start", "--task", "snap", "--branch", "feat/sn", "--scope", ".", "--done", "d"],
    )
    (git_repo / "x.txt").write_text("z", encoding="utf-8")
    r = CliRunner().invoke(app, ["snapshot", "--no-test"])
    assert r.exit_code == 0, r.output
    snaps = list((git_repo / "ignition_data/receipts").glob("snapshot-*.json"))
    assert snaps
    sess = next(git_repo.glob("ignition_data/sessions/*.json"))
    if sess.name == "current_session.json":
        sess = [p for p in git_repo.glob("ignition_data/sessions/*.json") if p.name != "current_session.json"][0]
    data = json.loads(sess.read_text(encoding="utf-8"))
    assert data.get("snapshots")


def test_risk_flags_in_receipt_scorecard(git_repo):
    CliRunner().invoke(
        app,
        ["start", "--task", "risk", "--branch", "feat/r", "--scope", ".", "--done", "d"],
    )
    (git_repo / "u.txt").write_text("u", encoding="utf-8")
    r = CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    assert r.exit_code == 0
    for p in (git_repo / "ignition_data/receipts").glob("*.json"):
        if p.name.startswith("recommend-"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("session_scorecard"):
            assert "risk_flags_count" in d["session_scorecard"] or d.get("decisions_v3", {}).get("risk_flags") is not None
            break
