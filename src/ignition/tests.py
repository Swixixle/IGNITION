"""Optional project test command execution from config."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ignition.utils import truncate


@dataclass
class TestRunResult:
    command: str | None
    exit_code: int | None
    stdout_summary: str
    stderr_summary: str
    skipped: bool
    reason: str | None = None


def run_test_command(
    repo_root: Path,
    command: str | None,
    *,
    shell: bool = True,
) -> TestRunResult:
    if not command or not command.strip():
        return TestRunResult(
            command=None,
            exit_code=None,
            stdout_summary="",
            stderr_summary="",
            skipped=True,
            reason="no test command configured",
        )
    cmd = command.strip()
    try:
        cp = subprocess.run(
            cmd,
            cwd=repo_root,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return TestRunResult(
            command=cmd,
            exit_code=cp.returncode,
            stdout_summary=truncate(cp.stdout or "", 4000),
            stderr_summary=truncate(cp.stderr or "", 4000),
            skipped=False,
        )
    except subprocess.TimeoutExpired:
        return TestRunResult(
            command=cmd,
            exit_code=None,
            stdout_summary="",
            stderr_summary="timed out after 600s",
            skipped=False,
        )
    except OSError as e:
        return TestRunResult(
            command=cmd,
            exit_code=None,
            stdout_summary="",
            stderr_summary=str(e),
            skipped=False,
        )
