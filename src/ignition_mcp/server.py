"""FastMCP server exposing the IGNITION CLI as MCP tools.

Every tool accepts an optional ``project_path`` so the same MCP server can
operate on any local repo without restart. When omitted, the server falls
back to ``$IGNITION_DEFAULT_PROJECT`` and finally to its own cwd.

Tools are grouped, in roughly the order users encounter them, into:

* setup / diagnostics: ``init``, ``doctor``, ``hook_print``
* daily loop:          ``begin``, ``start``, ``current``, ``status``,
                       ``checkpoint``, ``snapshot``, ``recommend``, ``stop``
* continuity:          ``resume``, ``list_sessions``, ``next``,
                       ``amend_context``, ``close_stale``
* review / handoff:    ``handoff``, ``ready``, ``timeline``, ``review``,
                       ``explain_session``, ``trends``, ``checklist``
* durability:          ``export``, ``import_bundle``, ``prune``
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ignition_mcp.exec import add_flag, run_ignition

mcp = FastMCP("ignition")


# ---------------------------------------------------------------------------
# Setup / diagnostics
# ---------------------------------------------------------------------------


@mcp.tool()
def ignition_init(project_path: str | None = None) -> dict[str, Any]:
    """Initialize IGNITION inside a project.

    Creates ``ignition.toml`` (if missing), session/receipt/template
    directories, detects the default branch, and embeds a suggested test
    command when one is obvious. Safe to run on a project that's already
    initialized — it will not clobber an existing config.
    """
    return run_ignition(["init"], project_path=project_path)


@mcp.tool()
def ignition_doctor(project_path: str | None = None) -> dict[str, Any]:
    """Run health checks on an IGNITION project.

    Reports pass/warn/fail for repo state, current-session pointer, required
    directories, the configured test command, worktree consistency, git
    identity, and untracked-file volume.
    """
    return run_ignition(["doctor", "--json"], project_path=project_path)


@mcp.tool()
def ignition_hook_print(
    shell: str = "zsh",
    project_path: str | None = None,
) -> dict[str, Any]:
    """Print optional shell aliases and a prompt-helper snippet.

    ``shell`` must be one of ``zsh``, ``bash``, or ``fish``. The output is
    printed only — IGNITION never edits rc files for you.
    """
    if shell not in {"zsh", "bash", "fish"}:
        raise ValueError("shell must be one of: zsh, bash, fish")
    return run_ignition(
        ["hook", "print", "--shell", shell],
        project_path=project_path,
    )


# ---------------------------------------------------------------------------
# Daily loop
# ---------------------------------------------------------------------------


@mcp.tool()
def ignition_begin(
    task: str,
    project_path: str | None = None,
    scope: str | None = None,
    print_assumptions: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Start a session via the daily-front-door command.

    Prefers ``begin`` over ``start``: blocks a duplicate unfinished session on
    the same branch, prints the last-stop "where you left off" line, and runs
    ``start`` with assumptions printed. Use ``force=True`` to override an
    active session on the same branch.
    """
    args: list[str] = ["begin", "--task", task, "--yes"]
    add_flag(args, "--scope", scope)
    add_flag(args, "--print-assumptions", print_assumptions)
    add_flag(args, "--force", force)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_start(
    task: str,
    project_path: str | None = None,
    scope: str | None = None,
    feature_branch: str | None = None,
    print_assumptions: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Start a new session explicitly (lower-level than ``begin``).

    Captures task, scope, and definition of done; optionally creates a
    feature branch; writes a session record and a receipt stub.
    """
    args: list[str] = ["start", "--task", task, "--yes"]
    add_flag(args, "--scope", scope)
    add_flag(args, "--feature-branch", feature_branch)
    add_flag(args, "--print-assumptions", print_assumptions)
    add_flag(args, "--force", force)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_current(project_path: str | None = None) -> dict[str, Any]:
    """One-line view of the active session: task, branch, duration, drift.

    Returns structured JSON suitable for prompt snippets and dashboards.
    """
    return run_ignition(["current", "--json"], project_path=project_path)


@mcp.tool()
def ignition_status(project_path: str | None = None) -> dict[str, Any]:
    """Full status block: scope drift, risk flags, recent commits, hints.

    Heavier than ``current``; use when you actually need to read the
    information rather than glance at it.
    """
    return run_ignition(["status", "--json"], project_path=project_path)


@mcp.tool()
def ignition_checkpoint(
    project_path: str | None = None,
    action: str = "note",
    note: str | None = None,
    run_tests: bool = False,
) -> dict[str, Any]:
    """Append a checkpoint to the active session.

    ``action`` is typically ``note``, ``commit``, or ``stash`` depending on
    how IGNITION is configured. Multi-line ``note`` strings can include
    structured tags (``todo:``, ``risk:``, ``question:``, ``followup:``)
    which IGNITION will parse into receipt metadata.
    """
    args: list[str] = ["checkpoint", "--action", action]
    add_flag(args, "--note", note)
    add_flag(args, "--test", run_tests)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_snapshot(
    project_path: str | None = None,
    run_tests: bool = False,
) -> dict[str, Any]:
    """Black-box recorder: append a timestamped snapshot to the active session.

    Records changed files, diff stat, HEAD, recent commits, and (optionally)
    a test run. Does not commit or stash.
    """
    args: list[str] = ["snapshot"]
    add_flag(args, "--test", run_tests)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_recommend(
    project_path: str | None = None,
    run_tests: bool = False,
) -> dict[str, Any]:
    """Rule-based "what should I do next?".

    Returns primary/secondary recommendation keys with reasons, risk flags,
    suggested commit messages, and example git lines. Never mutates git.
    """
    args: list[str] = ["recommend", "--json"]
    add_flag(args, "--test", run_tests)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_stop(
    project_path: str | None = None,
    parking: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Stop the active session with a parking choice and optional note.

    ``parking`` mirrors the CLI flag (e.g. ``note``, ``leave``, ``wip``,
    ``stash``, ``commit``). Writes the session receipt and clears the
    active-session pointer.
    """
    args: list[str] = ["stop"]
    add_flag(args, "--parking", parking)
    add_flag(args, "--note", note)
    return run_ignition(args, project_path=project_path)


# ---------------------------------------------------------------------------
# Continuity
# ---------------------------------------------------------------------------


@mcp.tool()
def ignition_resume(
    project_path: str | None = None,
    session_id: str | None = None,
    latest: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Rebind an unfinished session and print the last-stop carry-forward.

    Pass ``session_id`` to target a specific session, or ``latest=True`` to
    pick the most recent unfinished one on this branch.
    """
    args: list[str] = ["resume"]
    add_flag(args, "--session-id", session_id)
    add_flag(args, "--latest", latest)
    add_flag(args, "--force", force)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_list_sessions(
    project_path: str | None = None,
    limit: int | None = None,
    all_repos: bool = False,
) -> dict[str, Any]:
    """List recent sessions with status and timing.

    ``all_repos=True`` widens the listing past this clone when supported.
    """
    args: list[str] = ["list", "--json"]
    add_flag(args, "--limit", limit)
    add_flag(args, "--all", all_repos)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_next(project_path: str | None = None) -> dict[str, Any]:
    """Short "what was I doing?" from the last stopped session on this branch.

    Shows task, ending, parsed todos/risks/questions, suggested next, and a
    branch hygiene hint.
    """
    return run_ignition(["next", "--json"], project_path=project_path)


@mcp.tool()
def ignition_amend_context(
    project_path: str | None = None,
    session_id: str | None = None,
    task: str | None = None,
    scope: str | None = None,
    done: str | None = None,
    summary: str | None = None,
    todo: str | None = None,
    risk: str | None = None,
    question: str | None = None,
    followup: str | None = None,
) -> dict[str, Any]:
    """Edit the active session's context.

    All fields are optional; only the ones you pass are changed. ``todo``,
    ``risk``, ``question``, and ``followup`` append a single line each.
    """
    args: list[str] = ["amend-context"]
    add_flag(args, "--session-id", session_id)
    add_flag(args, "--task", task)
    add_flag(args, "--scope", scope)
    add_flag(args, "--done", done)
    add_flag(args, "--summary", summary)
    add_flag(args, "--todo", todo)
    add_flag(args, "--risk", risk)
    add_flag(args, "--question", question)
    add_flag(args, "--followup", followup)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_close_stale(
    project_path: str | None = None,
    days: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Mark old unfinished sessions as ``stale_closed`` (no deletion).

    Default cutoff lives in ``ignition.toml``; pass ``days`` to override.
    Use ``dry_run=True`` first to preview which sessions would be touched.
    """
    args: list[str] = ["close-stale"]
    add_flag(args, "--days", days)
    if dry_run:
        args.append("--dry-run")
    else:
        args.append("--yes")
    return run_ignition(args, project_path=project_path)


# ---------------------------------------------------------------------------
# Review / handoff
# ---------------------------------------------------------------------------


@mcp.tool()
def ignition_handoff(
    project_path: str | None = None,
    session_id: str | None = None,
    use_current: bool = True,
) -> dict[str, Any]:
    """Write a shareable handoff document for a session.

    Generates ``handoff-<session_id>.md`` and ``.json`` under
    ``ignition_data/receipts/``. Pass ``session_id`` to target a specific
    session, otherwise it operates on the current one.
    """
    args: list[str] = ["handoff", "--json"]
    if session_id:
        add_flag(args, "--session-id", session_id)
    elif use_current:
        args.append("--current")
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_ready(
    project_path: str | None = None,
    run_tests: bool = False,
) -> dict[str, Any]:
    """Heuristic merge-readiness check.

    Returns one of ``not_ready``, ``review_ready``, or
    ``merge_ready_candidate`` with a plain summary. This is a sniff test, not
    proof — review the details before acting on it.
    """
    args: list[str] = ["ready", "--json"]
    add_flag(args, "--test", run_tests)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_timeline(
    session_id: str,
    project_path: str | None = None,
) -> dict[str, Any]:
    """Timestamped timeline for one session: start → checkpoints → stop."""
    return run_ignition(
        ["timeline", session_id, "--json"],
        project_path=project_path,
    )


@mcp.tool()
def ignition_review(
    project_path: str | None = None,
    days: int | None = None,
    sessions: int | None = None,
    all_repos: bool = False,
) -> dict[str, Any]:
    """Roll up recent sessions for this repo.

    Defaults to the last 7 days. Returns counts, durations, file/test
    averages, status mix, scope-drift sessions, common recommendations and
    directories, and deterministic "patterns noticed" lines.
    """
    args: list[str] = ["review", "--json"]
    add_flag(args, "--days", days)
    add_flag(args, "--sessions", sessions)
    add_flag(args, "--all", all_repos)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_explain_session(
    session_id: str,
    project_path: str | None = None,
) -> dict[str, Any]:
    """One session in plain language.

    Task, branch, duration, what changed, scope/tests, how it ended, what
    was recommended, and what parking was chosen.
    """
    return run_ignition(
        ["explain-session", session_id, "--json"],
        project_path=project_path,
    )


@mcp.tool()
def ignition_trends(
    project_path: str | None = None,
    days: int | None = None,
    all_repos: bool = False,
) -> dict[str, Any]:
    """Numeric trends over a window (default 30 days).

    Sessions per week, averages, rates (clean / dirty / failing tests /
    scope drift), weekly bucket counts, short observations.
    """
    args: list[str] = ["trends", "--json"]
    add_flag(args, "--days", days)
    add_flag(args, "--all", all_repos)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_checklist(project_path: str | None = None) -> dict[str, Any]:
    """Print ``[project].merge_checklist`` and ``review_command`` if set."""
    return run_ignition(["checklist"], project_path=project_path)


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


@mcp.tool()
def ignition_export(
    project_path: str | None = None,
    days: int | None = None,
    all_sessions: bool = False,
    fmt: str = "json",
    compress: bool = False,
    output: str | None = None,
) -> dict[str, Any]:
    """Bundle sessions and receipt payloads to ``ignition_data/exports/``.

    ``fmt`` must be one of ``json``, ``jsonl``, or ``markdown-bundle``.
    """
    if fmt not in {"json", "jsonl", "markdown-bundle"}:
        raise ValueError("fmt must be one of: json, jsonl, markdown-bundle")
    args: list[str] = ["export", "--format", fmt]
    add_flag(args, "--days", days)
    add_flag(args, "--all", all_sessions)
    add_flag(args, "--compress", compress)
    add_flag(args, "-o", output)
    return run_ignition(args, project_path=project_path)


@mcp.tool()
def ignition_import_bundle(
    file: str,
    project_path: str | None = None,
) -> dict[str, Any]:
    """Merge an export file into this clone.

    Matches sessions on ``session_id`` and skips when local data looks newer.
    """
    return run_ignition(["import", file], project_path=project_path)


@mcp.tool()
def ignition_prune(project_path: str | None = None) -> dict[str, Any]:
    """Delete only disposable junk (``*.tmp`` and empty export stubs).

    Does **not** remove sessions or receipts.
    """
    return run_ignition(["prune"], project_path=project_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Launch the FastMCP server over stdio (the standard local transport)."""
    mcp.run()


if __name__ == "__main__":
    run()
