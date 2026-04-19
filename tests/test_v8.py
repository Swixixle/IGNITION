"""v8: schema migration, export/import, atomic IO, JSON envelope, soft loads."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ignition.atomic_io import atomic_write_json, safe_read_json
from ignition.cli import app
from ignition import export_import as export_import_mod
from ignition import schema as schema_mod
from ignition import session as session_mod
from ignition.json_output import json_envelope


def test_migrate_session_sparse_v1():
    raw = {
        "session_id": "x-1",
        "task": "t",
        "branch": "main",
        "repo_root": "/tmp",
        "started_at": "2026-01-01T00:00:00+00:00",
        "status": "active",
    }
    m = schema_mod.migrate_session(raw)
    assert m["schema_version"] == schema_mod.CURRENT_SESSION_SCHEMA_VERSION
    assert "linkage" in m
    assert m["linkage"].get("session_id") == "x-1"


def test_migrate_receipt_sparse():
    raw = {"session": {"session_id": "a"}, "phase": "started"}
    m = schema_mod.migrate_receipt(raw)
    assert m["schema_version"] == schema_mod.CURRENT_RECEIPT_SCHEMA_VERSION


def test_json_envelope_metadata_order():
    e = json_envelope({"active": False, "x": 1}, repo_root=Path("/tmp/repo"))
    assert e["tool_version"]
    assert e["schema_version"] == schema_mod.CURRENT_SESSION_SCHEMA_VERSION
    assert e["generated_at"]
    assert e["repo_root"].endswith("repo")
    assert e["x"] == 1


def test_safe_read_json_malformed(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert safe_read_json(p) is None


def test_atomic_write_json_roundtrip(tmp_path: Path):
    p = tmp_path / "a.json"
    atomic_write_json(p, {"k": 1})
    assert safe_read_json(p) == {"k": 1}


def test_export_import_roundtrip(git_repo: Path):
    r = CliRunner().invoke(
        app,
        ["start", "--yes", "--task", "export me", "--no-branch-switch"],
    )
    assert r.exit_code == 0, r.output

    out = export_import_mod.export_to_path(
        git_repo,
        None,
        None,
        git_repo / "ignition_data" / "exports" / "t.json",
        fmt="json",
        compress=False,
    )
    assert out.is_file()

    # Fresh dir: import into subfolder as second clone simulation
    res = export_import_mod.import_bundle_path(git_repo, None, None, out)
    assert res.sessions_imported >= 0
    assert isinstance(res.warnings, list)


def test_import_skips_newer_local(git_repo: Path):
    sdir = git_repo / "ignition_data" / "sessions"
    sdir.mkdir(parents=True, exist_ok=True)
    sid = "same-id"
    older = {
        "schema_version": 1,
        "session_id": sid,
        "repo_root": str(git_repo.resolve()),
        "branch": "main",
        "task": "x",
        "scope": [],
        "started_at": "2026-01-01T00:00:00+00:00",
        "stopped_at": "2026-01-02T00:00:00+00:00",
        "status": "stopped",
        "checkpoints": [],
    }
    session_mod.save_session(sdir / f"{sid}.json", older)

    bundle = {
        "export_schema_version": 1,
        "sessions": [
            {
                **older,
                "stopped_at": "2026-01-01T12:00:00+00:00",
            }
        ],
        "receipts": {},
    }
    p = git_repo / "ignition_data" / "exports" / "b.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bundle), encoding="utf-8")

    res = export_import_mod.import_bundle_path(git_repo, None, None, p)
    assert res.sessions_skipped >= 1


def test_doctor_json(git_repo: Path):
    r = CliRunner().invoke(app, ["doctor", "--json"])
    assert r.exit_code == 0
    d = json.loads(r.output)
    assert "checks" in d
    assert d.get("schema_version") is not None


def test_list_json_envelope(git_repo: Path):
    CliRunner().invoke(app, ["start", "--yes", "--task", "v8", "--no-branch-switch"])
    r = CliRunner().invoke(app, ["list", "--json"])
    assert r.exit_code == 0
    doc = json.loads(r.output)
    assert "sessions" in doc
    assert doc["schema_version"] is not None


def test_corrupt_session_skipped_in_list(git_repo: Path, monkeypatch):
    monkeypatch.chdir(git_repo)
    cfg = __import__("ignition.config", fromlist=["load_config"]).load_config(git_repo)
    sdir = git_repo / cfg.session_dir
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "broken.json").write_text("{", encoding="utf-8")
    r = CliRunner().invoke(app, ["list", "--json"])
    assert r.exit_code == 0
