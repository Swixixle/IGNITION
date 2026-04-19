"""Interactive prompts; every flow also supports flags for scripting."""

from __future__ import annotations

import typer


def prompt_task(default: str | None = None) -> str:
    v = typer.prompt("Task name", default=default or "")
    return v.strip()


def prompt_branch(default: str | None = None) -> str:
    v = typer.prompt("Feature branch name", default=default or "")
    return v.strip()


def prompt_scope_list() -> list[str]:
    raw = typer.prompt(
        "Target paths / scope (comma-separated, optional)",
        default="",
        show_default=False,
    )
    return split_scope(raw)


def prompt_definition_of_done(default: str | None = None) -> str:
    v = typer.prompt("Definition of done (optional)", default=default or "")
    return v.strip()


def split_scope(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def parse_scope_option(values: tuple[str, ...]) -> list[str]:
    parts: list[str] = []
    for v in values:
        parts.extend(split_scope(v))
    return parts


def prompt_dirty_resolution() -> str:
    typer.echo("Working tree has uncommitted changes.")
    typer.echo("  [k]eep — include them in this session")
    typer.echo("  [s]tash — stash before continuing")
    typer.echo("  [a]bort — cancel start")
    choice = typer.prompt("Choose", default="k").strip().lower()
    if choice in ("k", "keep", ""):
        return "keep"
    if choice in ("s", "stash"):
        return "stash"
    if choice in ("a", "abort", "q", "quit"):
        return "abort"
    return "keep"


def prompt_checkpoint_action() -> str:
    typer.echo("Checkpoint action:")
    typer.echo("  [w] WIP commit (add + commit)")
    typer.echo("  [s] Stash including untracked")
    typer.echo("  [n] Note only (no Git mutation)")
    choice = typer.prompt("Choose", default="n").strip().lower()
    if choice in ("w", "wip"):
        return "wip"
    if choice in ("s", "stash"):
        return "stash"
    return "note"


def prompt_stop_parking() -> str:
    typer.echo("How should we park this session?")
    typer.echo("  [l]eave as-is")
    typer.echo("  [w] WIP commit")
    typer.echo("  [c]lean final commit (you will edit message in editor if configured)")
    typer.echo("  [s]tash unfinished work")
    typer.echo("  [n]ote only")
    choice = typer.prompt("Choose", default="l").strip().lower()
    if choice in ("w", "wip"):
        return "wip"
    if choice in ("c", "commit", "clean"):
        return "commit"
    if choice in ("s", "stash"):
        return "stash"
    if choice in ("n", "note"):
        return "note"
    return "leave"
