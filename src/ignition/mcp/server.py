"""IGNITION MCP server entry point.

Run with ``ignition-mcp`` (after ``pip install -e ".[mcp]"``).

The server name is ``ignition``; tool names retain the ``ignition_`` prefix
so they stay unambiguous in multi-MCP agent transcripts (where bare
``current`` or ``begin`` would collide with other servers).
"""

from __future__ import annotations

import logging
import sys


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise SystemExit(
            'Install MCP support: pip install "ignition[mcp]"'
        ) from e

    from ignition.mcp import tools as t

    app = FastMCP("ignition")

    # Core tools — names match what tool-wizard SKILL.md calls.
    app.tool()(t.ignition_current)
    app.tool()(t.ignition_next)
    app.tool()(t.ignition_status)
    app.tool()(t.ignition_init)
    app.tool()(t.ignition_begin)
    app.tool()(t.ignition_resume)

    app.run(transport="stdio")


if __name__ == "__main__":
    main()
