"""Subprocess helper for shelling out to the ``ignition`` CLI.

The MCP server uses one helper, :func:`run_ignition`, so behaviour around
project-path resolution, JSON parsing, timeouts, and error formatting stays
consistent across every tool.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

# Default timeout for any single CLI invocation (seconds). Long enough for
# ``ignition export`` on a busy repo, short enough to surface hangs.
DEFAULT_TIMEOUT_S = 90

# Environment variable a user / host can set to make tools default to a
# specific repo when ``project_path`` is omitted. Mirrors Keysmith's
# ``KEYSMITH_DEFAULT_PROJECT`` convention.
DEFAULT_PROJECT_ENV = "IGNITION_DEFAULT_PROJECT"


class IgnitionError(RuntimeError):
    """Raised when the ``ignition`` CLI exits non-zero or cannot be found."""


def _ignition_executable() -> str:
    """Locate the ``ignition`` console script on PATH.

    Falls back to ``python -m ignition.cli`` style invocation only as a last
    resort; if that ever becomes load-bearing the wrapper should be reviewed.
    """
    exe = shutil.which("ignition")
    if exe:
        return exe
    raise IgnitionError(
        "Could not find the 'ignition' CLI on PATH. Install IGNITION "
        "(`pip install -e \".[mcp]\"` from the IGNITION repo) and ensure the "
        "Python environment hosting this MCP server can see it."
    )


def resolve_project_path(project_path: str | None) -> Path:
    """Resolve which directory ``ignition`` should run inside.

    Priority order:

    1. The explicit ``project_path`` argument.
    2. The ``IGNITION_DEFAULT_PROJECT`` environment variable.
    3. The current working directory of the MCP server process.

    The resolved path must exist and be a directory. Resolving to a non-repo
    directory is intentionally allowed — ``ignition init`` and ``ignition
    doctor`` are how you'd discover that.
    """
    if project_path:
        candidate = Path(project_path).expanduser()
    else:
        env_value = os.environ.get(DEFAULT_PROJECT_ENV, "").strip()
        candidate = Path(env_value).expanduser() if env_value else Path.cwd()

    resolved = candidate.resolve()
    if not resolved.exists():
        raise IgnitionError(f"project_path does not exist: {resolved}")
    if not resolved.is_dir():
        raise IgnitionError(f"project_path is not a directory: {resolved}")
    return resolved


def run_ignition(
    args: Sequence[str],
    *,
    project_path: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    """Invoke ``ignition <args>`` inside ``project_path`` and return a dict.

    The returned dict always contains:

    * ``cwd``            — the resolved project path used for the call
    * ``exit_code``      — the CLI exit code (0 on success)
    * ``stderr``         — stripped stderr (often a hint when exit_code != 0)
    * exactly one of ``json`` or ``stdout`` — parsed JSON when the CLI emitted
      a JSON envelope, raw stdout text otherwise.

    Raises :class:`IgnitionError` if the CLI exits non-zero so MCP hosts can
    surface the failure cleanly to the model.
    """
    cwd = resolve_project_path(project_path)
    exe = _ignition_executable()

    try:
        proc = subprocess.run(
            [exe, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin_text,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise IgnitionError(
            f"ignition {' '.join(args)} timed out after {timeout}s in {cwd}"
        ) from exc
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise IgnitionError(f"ignition executable not found: {exe}") from exc

    result: dict[str, Any] = {
        "cwd": str(cwd),
        "exit_code": proc.returncode,
        "stderr": (proc.stderr or "").strip(),
    }

    stdout = proc.stdout or ""
    stripped = stdout.strip()
    if stripped:
        try:
            result["json"] = json.loads(stripped)
        except json.JSONDecodeError:
            result["stdout"] = stdout
    else:
        result["stdout"] = ""

    if proc.returncode != 0:
        detail = result["stderr"] or result.get("stdout") or stripped
        raise IgnitionError(
            f"ignition {' '.join(args)} exited {proc.returncode}: {detail}"
        )

    return result


def add_flag(args: list[str], flag: str, value: Any) -> None:
    """Append ``--flag value`` to ``args`` only when ``value`` is meaningful.

    Skips ``None``, empty strings, and empty sequences. Booleans are treated
    as switches: ``True`` appends just ``--flag``, ``False`` appends nothing.
    """
    if value is None:
        return
    if isinstance(value, bool):
        if value:
            args.append(flag)
        return
    if isinstance(value, str):
        if value == "":
            return
        args.extend([flag, value])
        return
    if isinstance(value, (list, tuple)):
        if not value:
            return
        args.extend([flag, ",".join(str(v) for v in value)])
        return
    args.extend([flag, str(value)])
