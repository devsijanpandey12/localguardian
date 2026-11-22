"""Smoke tests verifying LocalGuardian's MCP server builds cleanly on mcp 2.x / 1.x."""

from __future__ import annotations

from localguardian.mcp_server import create_mcp_server


def test_mcp_server_initializes_with_safe_tools() -> None:
    server = create_mcp_server(dry_run=True)
    assert server is not None
    assert server.name == "localguardian"
