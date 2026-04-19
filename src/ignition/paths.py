"""Filesystem paths for IGNITION data relative to a repository root."""

from __future__ import annotations

from pathlib import Path


DEFAULT_SESSION_DIR = "ignition_data/sessions"
DEFAULT_RECEIPT_DIR = "ignition_data/receipts"
DEFAULT_TEMPLATES_DIR = "ignition_data/templates"
DEFAULT_EXPORTS_DIR = "ignition_data/exports"
CONFIG_FILENAME = "ignition.toml"
ACTIVE_SESSION_FILE = "current_session.json"


def repo_root_from(path: Path | None = None) -> Path:
    """Return absolute path; when given, resolve starting from `path`."""
    base = (path or Path.cwd()).resolve()
    return base


def session_dir(repo_root: Path, configured: str | None) -> Path:
    rel = configured or DEFAULT_SESSION_DIR
    return (repo_root / rel).resolve()


def receipt_dir(repo_root: Path, configured: str | None) -> Path:
    rel = configured or DEFAULT_RECEIPT_DIR
    return (repo_root / rel).resolve()


def templates_dir(repo_root: Path, configured: str | None) -> Path:
    rel = configured or DEFAULT_TEMPLATES_DIR
    return (repo_root / rel).resolve()


def exports_dir(repo_root: Path) -> Path:
    """Bundled exports (backup / portability); fixed under repo root."""
    return (repo_root / DEFAULT_EXPORTS_DIR).resolve()


def config_path(repo_root: Path) -> Path:
    return repo_root / CONFIG_FILENAME


def active_session_path(repo_root: Path, session_dir_rel: str | None) -> Path:
    return session_dir(repo_root, session_dir_rel) / ACTIVE_SESSION_FILE


def ensure_data_dirs(repo_root: Path, session_rel: str | None, receipt_rel: str | None) -> None:
    sdir = session_dir(repo_root, session_rel)
    rdir = receipt_dir(repo_root, receipt_rel)
    sdir.mkdir(parents=True, exist_ok=True)
    rdir.mkdir(parents=True, exist_ok=True)
