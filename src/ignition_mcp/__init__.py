"""IGNITION MCP server.

Wraps the existing ``ignition`` CLI as Model Context Protocol tools so that
MCP-aware hosts (Cowork, Claude Desktop, Claude Code, etc.) can drive
session-control commands against any local repository.

The server is intentionally a *thin* wrapper: each tool shells out to
``ignition <subcommand>`` with ``--json`` where supported, and returns the
parsed envelope. Internals of the ``ignition`` package are not imported, so
this module stays decoupled from IGNITION's private API.
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> None:
    """Entry point used by the ``ignition-mcp`` console script."""
    from ignition_mcp.server import run

    run()
