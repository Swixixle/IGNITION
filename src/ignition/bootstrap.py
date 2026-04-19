"""`ignition init`: create config and data dirs with sensible defaults (no shell mutation)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ignition import git_ops
from ignition.paths import CONFIG_FILENAME, ensure_data_dirs, receipt_dir, session_dir, templates_dir


def detect_suggested_test_command(repo_root: Path) -> str | None:
    """Best-effort detect a test command; does not run anything."""
    pr = repo_root / "pyproject.toml"
    if pr.is_file():
        text = pr.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\[tool\.pytest", text) or "pytest" in text.lower():
            return "pytest -q"
    if (repo_root / "pytest.ini").is_file() or (repo_root / "setup.cfg").is_file():
        return "pytest -q"
    pkg = repo_root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = (data or {}).get("scripts") or {}
            if isinstance(scripts, dict) and scripts.get("test"):
                return "npm test"
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    mk = repo_root / "Makefile"
    if mk.is_file() and re.search(r"^test\s*:", mk.read_text(encoding="utf-8", errors="replace"), re.MULTILINE):
        return "make test"
    return None


def shell_init_snippet(shell: str) -> str:
    """One-line hint for ~/.zshrc etc. (printed only; never written automatically)."""
    if shell == "fish":
        return "# Add to ~/.config/fish/config.fish — see: ignition hook print --shell fish"
    if shell == "bash":
        return "# Add to ~/.bashrc — see: ignition hook print --shell bash"
    return "# Add to ~/.zshrc — see: ignition hook print --shell zsh"


@dataclass
class InitResult:
    created_config: bool
    config_path: Path
    session_dir: Path
    receipt_dir: Path
    templates_dir: Path
    default_branch: str
    suggested_test: str | None
    repo_name: str


def run_init(repo_root: Path, cfg_session: str | None, cfg_receipt: str | None, cfg_templates: str | None) -> InitResult:
    default_br = git_ops.detect_default_branch(repo_root) or "main"
    suggested = detect_suggested_test_command(repo_root)
    sdir = session_dir(repo_root, cfg_session)
    rdir = receipt_dir(repo_root, cfg_receipt)
    tdir = templates_dir(repo_root, cfg_templates)
    ensure_data_dirs(repo_root, cfg_session, cfg_receipt)
    tdir.mkdir(parents=True, exist_ok=True)

    cfg_path = repo_root / CONFIG_FILENAME
    created = False
    if not cfg_path.is_file():
        lines = [
            f'# IGNITION — session boundaries around Git (repo: {repo_root.name})',
            f'default_branch = "{default_br}"',
            'default_feature_branch_prefix = "feature/"',
            "plain_language = false",
            "recommendation_mode = \"balanced\"",
            'receipt_template = "default"',
            "",
            "# Uncomment to run tests on checkpoint/status when you do not pass --no-test:",
        ]
        if suggested:
            lines.append(f'auto_checkpoint_test_command = "{suggested}"')
            lines.append(f'auto_status_test_command = "{suggested}"')
        else:
            lines.append('# auto_checkpoint_test_command = "pytest -q"')
            lines.append('# auto_status_test_command = "pytest -q"')
        lines.extend(
            [
                "",
                "# Per-project defaults (optional):",
                "# [project]",
                '# preferred_scope = ["src/", "tests/"]',
                '# test_command = "pytest -q"   # used if top-level test commands are unset',
                '# feature_prefix = "feature/"',
                "",
            ]
        )
        cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        created = True

    return InitResult(
        created_config=created,
        config_path=cfg_path,
        session_dir=sdir,
        receipt_dir=rdir,
        templates_dir=tdir,
        default_branch=default_br,
        suggested_test=suggested,
        repo_name=repo_root.name,
    )
