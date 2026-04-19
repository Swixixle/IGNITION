"""v6: handoff, ready, timeline, note tags, hygiene hints."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ignition.cli import app
from ignition import handoff as handoff_mod
from ignition import hygiene as hygiene_mod
from ignition import notes_tags
from ignition import ready as ready_mod
from ignition import timeline as timeline_mod
from ignition.checkpoint import make_checkpoint_record
from ignition.config import load_config, IgnitionConfig
from ignition import decisions as decisions_mod


def test_parse_note_tags_multiline():
    text = """todo: fix edge case
risk: flaky network
question: split PR?
followup: ask reviewer
noise line without tag
"""
    t = notes_tags.parse_note_tags(text)
    assert "fix edge case" in t["todo"]
    assert any("flaky" in x for x in t["risk"])
    assert t["question"]
    assert t["followup"]


def test_ready_assess_not_ready_dirty():
    cfg = IgnitionConfig()
    bundle = decisions_mod.DecisionBundle(
        primary_key="safe_to_commit_cleanly",
        secondary_keys=[],
        primary_reason="ok",
        secondary_reasons=[],
        recommendation_keys=[],
        risk_flags=[],
        split_changes_hint=False,
        split_changes_reason=None,
        suggested_clean_message="m",
        suggested_wip_message="w",
        git_commands=[],
        scorecard={},
    )
    import tempfile

    tmp = Path(tempfile.mkdtemp())

    r = ready_mod.assess_readiness(
        tmp,
        cfg,
        {"branch": "main"},
        test_result_dict={"exit_code": 0, "skipped": False},
        final_status="dirty_uncommitted",
        files_changed=["a.py"],
        scope_out_count=0,
        bundle=bundle,
        working_tree_clean=False,
    )
    assert r.state == "not_ready"


def test_timeline_ordering():
    sess = {
        "session_id": "x",
        "started_at": "2026-01-01T10:00:00+00:00",
        "checkpoints": [{"at": "2026-01-01T11:00:00+00:00", "note": "n"}],
        "recommend_events": [{"at": "2026-01-01T11:30:00+00:00", "primary_recommendation": "fix_tests_first"}],
        "stopped_at": "2026-01-01T12:00:00+00:00",
        "final_status": "clean_complete",
    }
    ev = timeline_mod.build_timeline(sess)
    types = [e["type"] for e in ev]
    assert types[0] == "start"
    assert "checkpoint" in types
    assert "recommend" in types
    assert types[-1] == "stop"


def test_handoff_writes_files(git_repo: Path):
    CliRunner().invoke(
        app,
        ["start", "--yes", "--task", "handoff test", "--no-branch-switch"],
    )
    r = CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    assert r.exit_code == 0, r.output
    # find session id from list
    lr = CliRunner().invoke(app, ["list", "--json"])
    doc = json.loads(lr.output.strip())
    rows = doc.get("sessions", doc)
    sid = next(x["session_id"] for x in rows if x.get("task") == "handoff test")
    h = CliRunner().invoke(app, ["handoff", "--session-id", sid])
    assert h.exit_code == 0, h.output
    assert list((git_repo / "ignition_data" / "receipts").glob(f"handoff-{sid}.md"))


def test_checkpoint_note_tags_in_record():
    rec = make_checkpoint_record(
        changed_files=[],
        diff_stat="",
        test_result=None,
        wip_commit_hash=None,
        stash_message=None,
        note="risk: boom\ntodo: fix",
        head_hash="abc",
        note_tags=notes_tags.parse_note_tags("risk: boom\ntodo: fix"),
    )
    assert rec["note_tags"]["risk"]


def test_hygiene_sessions_on_branch(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "a", "--no-branch-switch"])
    CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    cfg = load_config(git_repo)
    n = hygiene_mod.count_sessions_on_branch(git_repo, cfg.session_dir, "main")
    assert n >= 1


def test_receipt_has_readiness_fields_after_stop(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "r", "--no-branch-switch"])
    CliRunner().invoke(app, ["stop", "--no-test", "--parking", "leave"])
    cfg = load_config(git_repo)
    for p in (git_repo / "ignition_data" / "receipts").glob("*.json"):
        if p.name.startswith("handoff-") or p.name.startswith("recommend-"):
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("session", {}).get("task") == "r":
            assert "readiness_state" in data
            assert "handoff_summary" in data
            break
    else:
        raise AssertionError("receipt not found")
