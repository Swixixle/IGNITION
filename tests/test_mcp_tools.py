"""Smoke tests for the IGNITION MCP tool wrappers.

These exercise project-path resolution, init clobber/force semantics, and
error paths without requiring a real Git repository. Full integration is
covered by manual smoke-test (run ``ignition-mcp`` against a real repo
and call the tools from an agent client).
"""

from __future__ import annotations

from ignition.mcp import tools


def test_resolve_project_default(monkeypatch):
    monkeypatch.delenv("IGNITION_DEFAULT_PROJECT", raising=False)
    p = tools._resolve_project(None)
    assert p.exists()


def test_resolve_project_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("IGNITION_DEFAULT_PROJECT", str(tmp_path))
    p = tools._resolve_project(None)
    assert p == tmp_path.resolve()


def test_resolve_project_explicit(tmp_path):
    p = tools._resolve_project(str(tmp_path))
    assert p == tmp_path.resolve()


def test_resolve_project_blank_falls_back_to_env(monkeypatch, tmp_path):
    monkeypatch.setenv("IGNITION_DEFAULT_PROJECT", str(tmp_path))
    p = tools._resolve_project("   ")
    assert p == tmp_path.resolve()


def test_current_returns_inactive_for_empty_dir(tmp_path):
    out = tools.ignition_current(project_path=str(tmp_path))
    assert out.get("active") is False
    assert out.get("repo_root") == str(tmp_path.resolve())


def test_current_errors_for_nonexistent_path(tmp_path):
    bad = tmp_path / "does_not_exist"
    out = tools.ignition_current(project_path=str(bad))
    assert "error" in out


def test_init_creates_config(tmp_path):
    out = tools.ignition_init(project_path=str(tmp_path))
    assert out.get("status") == "initialized"
    assert (tmp_path / "ignition.toml").is_file()


def test_init_refuses_to_clobber(tmp_path):
    tools.ignition_init(project_path=str(tmp_path))
    out = tools.ignition_init(project_path=str(tmp_path))
    assert out.get("status") == "already_initialized"
    assert out.get("path", "").endswith("ignition.toml")


def test_init_force_overwrites(tmp_path):
    tools.ignition_init(project_path=str(tmp_path))
    out = tools.ignition_init(project_path=str(tmp_path), force=True)
    assert out.get("status") == "initialized"


def test_begin_requires_task(tmp_path):
    out = tools.ignition_begin(task="", project_path=str(tmp_path))
    assert "error" in out
    out2 = tools.ignition_begin(task="   ", project_path=str(tmp_path))
    assert "error" in out2


def test_all_tools_exposed():
    expected = {
        "ignition_current",
        "ignition_next",
        "ignition_status",
        "ignition_init",
        "ignition_begin",
        "ignition_resume",
    }
    actual = {fn.__name__ for fn in tools.ALL_TOOLS}
    assert actual == expected
