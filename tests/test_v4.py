"""v4: review, explain-session, trends, normalization of old receipts, plain_language."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from ignition.cli import app
from ignition.config import load_config
from ignition.explain import explain_session_json, explain_session_text, load_session_payload
from ignition.normalize import normalize_record
from ignition.paths import receipt_dir
from ignition.review import build_review, filter_by_days, iter_session_records
from ignition.trends import build_trends


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _write_minimal_receipt(
    repo_root: Path,
    *,
    session_id: str,
    started: datetime,
    ended: datetime,
    repo_rr: str | None = None,
    extra: dict | None = None,
) -> Path:
    rr = repo_rr if repo_rr is not None else str(repo_root.resolve())
    rdir = receipt_dir(repo_root, None)
    rdir.mkdir(parents=True, exist_ok=True)
    body = {
        "session": {
            "session_id": session_id,
            "repo_root": rr,
            "repo_name": "test-repo",
            "started_at": _iso(started),
            "ended_at": _iso(ended),
            "task": "do thing",
            "branch": "main",
        },
        "final_status": "clean_complete",
        "files_changed": ["src/a.py"],
        "file_stats": {"untracked_count": 1},
        "test_result": {"exit_code": 0, "skipped": False},
        "decisions_v3": {
            "primary_recommendation": "safe_to_commit_cleanly",
            "primary_reason": "tests passed",
        },
        "suggested_next_action": "commit and push when ready",
    }
    if extra:
        body.update(extra)
    path = rdir / f"{session_id}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_normalize_minimal_record_no_crash():
    n = normalize_record({})
    assert "files_changed_count" in n
    assert n.get("files_changed_count") == 0


def test_build_review_aggregates_recent_sessions(git_repo: Path):
    now = datetime.now(timezone.utc)
    for i in range(3):
        _write_minimal_receipt(
            git_repo,
            session_id=f"sess-{i}",
            started=now - timedelta(days=i, hours=2),
            ended=now - timedelta(days=i, hours=1),
        )
    cfg = load_config(git_repo)
    out = build_review(git_repo, cfg.session_dir, cfg.receipt_dir, days=7)
    assert out["session_count"] == 3
    assert out["tests_run_count"] == 3
    assert out["tests_pass_count"] == 3
    assert out["average_files_changed"] >= 0
    assert out["most_common_primary_recommendation"] == "safe_to_commit_cleanly"
    assert any("primary recommendation" in p.lower() for p in out["patterns_noticed"])


def test_old_receipt_sparse_fields_does_not_crash_review(git_repo: Path):
    rdir = receipt_dir(git_repo, None)
    rdir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    sparse = {
        "session": {
            "session_id": "legacy",
            "repo_root": str(git_repo.resolve()),
            "started_at": _iso(now - timedelta(days=1)),
            "ended_at": _iso(now - timedelta(hours=1)),
        },
        "final_status": "dirty_uncommitted",
        # no files_changed, decisions_v3, test_result
    }
    (rdir / "legacy.json").write_text(json.dumps(sparse), encoding="utf-8")
    cfg = load_config(git_repo)
    out = build_review(git_repo, cfg.session_dir, cfg.receipt_dir, days=7)
    assert out["session_count"] == 1
    assert isinstance(out["patterns_noticed"], list)  # rule-based; may be empty for n=1
    tr = build_trends(git_repo, cfg.session_dir, cfg.receipt_dir, days=7)
    assert tr["session_count"] == 1


def test_build_trends_multiple_sessions(git_repo: Path):
    now = datetime.now(timezone.utc)
    for i in range(4):
        _write_minimal_receipt(
            git_repo,
            session_id=f"t{i}",
            started=now - timedelta(days=5 - i),
            ended=now - timedelta(days=5 - i, minutes=-30),
        )
    cfg = load_config(git_repo)
    t = build_trends(git_repo, cfg.session_dir, cfg.receipt_dir, days=30)
    assert t["session_count"] == 4
    assert t["sessions_per_week"] > 0
    assert "averages" in t and t["averages"].get("duration_minutes") is not None
    assert "rates" in t


def test_explain_session_readable_and_json(git_repo: Path):
    now = datetime.now(timezone.utc)
    _write_minimal_receipt(
        git_repo,
        session_id="explain-me",
        started=now - timedelta(hours=2),
        ended=now - timedelta(hours=1),
    )
    cfg = load_config(git_repo)
    raw = load_session_payload(git_repo, "explain-me", cfg.session_dir, cfg.receipt_dir)
    assert raw is not None
    text = explain_session_text(raw, plain_language=False)
    assert "branch" in text.lower() or "main" in text
    assert "safe_to_commit_cleanly" in text or "IGNITION recommended" in text
    j = explain_session_json(raw)
    assert j["session_id"] == "explain-me"
    assert "plain_summary" in j and "technical_summary" in j


def test_explain_plain_language_softer_wording():
    now = datetime.now(timezone.utc)
    r = normalize_record(
        {
            "session": {
                "session_id": "p",
                "repo_name": "r",
                "branch": "main",
                "started_at": _iso(now - timedelta(hours=1)),
                "ended_at": _iso(now),
                "task": "x",
            },
            "files_changed_count": 2,
            "final_status": "clean_complete",
            "scope_in_count": 1,
            "scope_out_count": 0,
        }
    )
    plain = explain_session_text(r, plain_language=True)
    tech = explain_session_text(r, plain_language=False)
    assert "path(s) had local changes" in plain or "local changes" in plain
    assert "Files touched" in tech or "path(s)" in tech


def test_filter_by_days_drops_old(git_repo: Path):
    now = datetime.now(timezone.utc)
    _write_minimal_receipt(
        git_repo,
        session_id="new",
        started=now - timedelta(days=2),
        ended=now - timedelta(days=2, minutes=-30),
    )
    rdir = receipt_dir(git_repo, None)
    (rdir / "old.json").write_text(
        json.dumps(
            {
                "session": {
                    "session_id": "old",
                    "repo_root": str(git_repo.resolve()),
                    "started_at": _iso(now - timedelta(days=20)),
                    "ended_at": _iso(now - timedelta(days=20, minutes=-30)),
                    "task": "t",
                    "branch": "main",
                },
                "final_status": "clean_complete",
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(git_repo)
    recs = iter_session_records(git_repo, cfg.session_dir, cfg.receipt_dir, all_repos=False)
    assert len(recs) >= 2
    recent = filter_by_days(recs, 7)
    ids = {(x.get("session") or {}).get("session_id") or x.get("session_id") for x in recent}
    assert "new" in ids
    assert "old" not in ids


def test_cli_review_explain_trends(git_repo: Path):
    now = datetime.now(timezone.utc)
    _write_minimal_receipt(
        git_repo,
        session_id="cli-s",
        started=now - timedelta(days=1),
        ended=now - timedelta(hours=2),
    )
    runner = CliRunner()
    r = runner.invoke(app, ["review", "--days", "7"])
    assert r.exit_code == 0, r.output
    assert "Sessions in window" in r.output or "session_count" in r.output

    e = runner.invoke(app, ["explain-session", "cli-s"])
    assert e.exit_code == 0, e.output
    assert "Task:" in e.output or "task" in e.output.lower()

    t = runner.invoke(app, ["trends", "--days", "30"])
    assert t.exit_code == 0, t.output


def test_plain_language_config_file(git_repo: Path):
    (git_repo / "ignition.toml").write_text("plain_language = true\n", encoding="utf-8")
    now = datetime.now(timezone.utc)
    _write_minimal_receipt(
        git_repo,
        session_id="pl",
        started=now - timedelta(hours=1),
        ended=now,
    )
    runner = CliRunner()
    out = runner.invoke(app, ["explain-session", "pl"])
    assert out.exit_code == 0
    # Plain mode prefers softer file line
    assert "path(s) had local changes" in out.output or "What changed" in out.output
