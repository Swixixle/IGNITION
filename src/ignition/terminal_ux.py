"""Small helpers for grouped CLI output."""

from __future__ import annotations

import typer


def section_header(title: str) -> None:
    typer.echo("")
    typer.secho(f"── {title} ──", fg=typer.colors.BRIGHT_BLACK, bold=False)
