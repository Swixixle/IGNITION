"""Load `ignition.toml` from repository root (optional)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ignition.paths import DEFAULT_RECEIPT_DIR, DEFAULT_SESSION_DIR, DEFAULT_TEMPLATES_DIR


@dataclass
class IgnitionConfig:
    default_branch: str = "main"
    default_feature_branch_prefix: str = "feature/"
    auto_checkpoint_test_command: str | None = None
    auto_status_test_command: str | None = None
    session_dir: str = DEFAULT_SESSION_DIR
    receipt_dir: str = DEFAULT_RECEIPT_DIR
    templates_dir: str = DEFAULT_TEMPLATES_DIR
    receipt_markdown_template: str | None = None
    warn_on_scope_drift: bool = True
    max_files_before_warning: int = 8
    max_recent_commits: int = 5
    scope_drift_preview_limit: int = 5
    untracked_warning_threshold: int = 10
    recommendation_mode: str = "balanced"
    long_session_minutes: int = 180
    many_commits_threshold: int = 8
    large_untracked_threshold: int = 15
    split_change_directory_threshold: int = 3
    receipt_template: str = "default"
    plain_language: bool = False
    preferred_scope: list[str] = field(default_factory=list)
    merge_checklist: list[str] = field(default_factory=list)
    review_command: str | None = None
    common_paths: list[str] = field(default_factory=list)
    notes_style: str | None = None


def load_config(repo_root: Path) -> IgnitionConfig:
    path = repo_root / "ignition.toml"
    if not path.is_file():
        return IgnitionConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg = IgnitionConfig()
    if "default_branch" in data:
        cfg.default_branch = str(data["default_branch"])
    if "default_feature_branch_prefix" in data:
        cfg.default_feature_branch_prefix = str(data["default_feature_branch_prefix"])
    if "auto_checkpoint_test_command" in data and data["auto_checkpoint_test_command"]:
        cfg.auto_checkpoint_test_command = str(data["auto_checkpoint_test_command"])
    if "auto_status_test_command" in data and data["auto_status_test_command"]:
        cfg.auto_status_test_command = str(data["auto_status_test_command"])
    if "session_dir" in data:
        cfg.session_dir = str(data["session_dir"])
    if "receipt_dir" in data:
        cfg.receipt_dir = str(data["receipt_dir"])
    if "templates_dir" in data:
        cfg.templates_dir = str(data["templates_dir"])
    if "receipt_markdown_template" in data and data["receipt_markdown_template"]:
        cfg.receipt_markdown_template = str(data["receipt_markdown_template"])
    if "warn_on_scope_drift" in data:
        cfg.warn_on_scope_drift = bool(data["warn_on_scope_drift"])
    if "max_files_before_warning" in data:
        cfg.max_files_before_warning = int(data["max_files_before_warning"])
    if "max_recent_commits" in data:
        cfg.max_recent_commits = int(data["max_recent_commits"])
    if "scope_drift_preview_limit" in data:
        cfg.scope_drift_preview_limit = int(data["scope_drift_preview_limit"])
    if "untracked_warning_threshold" in data:
        cfg.untracked_warning_threshold = int(data["untracked_warning_threshold"])
    if "recommendation_mode" in data:
        cfg.recommendation_mode = str(data["recommendation_mode"])
    if "long_session_minutes" in data:
        cfg.long_session_minutes = int(data["long_session_minutes"])
    if "many_commits_threshold" in data:
        cfg.many_commits_threshold = int(data["many_commits_threshold"])
    if "large_untracked_threshold" in data:
        cfg.large_untracked_threshold = int(data["large_untracked_threshold"])
    if "split_change_directory_threshold" in data:
        cfg.split_change_directory_threshold = int(data["split_change_directory_threshold"])
    if "receipt_template" in data:
        cfg.receipt_template = str(data["receipt_template"])
    if "plain_language" in data:
        cfg.plain_language = bool(data["plain_language"])

    proj = data.get("project")
    if isinstance(proj, dict):
        if "preferred_scope" in proj and isinstance(proj["preferred_scope"], list):
            cfg.preferred_scope = [str(x) for x in proj["preferred_scope"]]
        if "test_command" in proj and proj["test_command"]:
            tc = str(proj["test_command"])
            cfg.auto_checkpoint_test_command = tc
            cfg.auto_status_test_command = tc
        if "feature_prefix" in proj:
            cfg.default_feature_branch_prefix = str(proj["feature_prefix"])
        if "receipt_template" in proj:
            cfg.receipt_template = str(proj["receipt_template"])
        if "plain_language" in proj:
            cfg.plain_language = bool(proj["plain_language"])
        if "recommendation_mode" in proj:
            cfg.recommendation_mode = str(proj["recommendation_mode"])
        if "merge_checklist" in proj and isinstance(proj["merge_checklist"], list):
            cfg.merge_checklist = [str(x) for x in proj["merge_checklist"]]
        if "review_command" in proj:
            v = proj["review_command"]
            cfg.review_command = str(v) if v else None
        if "common_paths" in proj and isinstance(proj["common_paths"], list):
            cfg.common_paths = [str(x) for x in proj["common_paths"]]
        if "notes_style" in proj and proj["notes_style"] is not None:
            cfg.notes_style = str(proj["notes_style"])
        if "preferred_branch_prefix" in proj:
            cfg.default_feature_branch_prefix = str(proj["preferred_branch_prefix"])
    return cfg


def effective_status_test_command(cfg: IgnitionConfig) -> str | None:
    return cfg.auto_status_test_command or cfg.auto_checkpoint_test_command
