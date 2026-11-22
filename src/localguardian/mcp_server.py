"""LocalGuardian MCP Server (compatible with mcp 2.x MCPServer and mcp 1.x FastMCP).

Exposes all safety-gated Windows OS, window management, and Google Chrome tools
over standard Model Context Protocol (MCP) stdio transport.
"""

from __future__ import annotations

from typing import Optional

from localguardian.config import LocalGuardianConfig, load_config
from localguardian.safety.audit import AuditLogger
from localguardian.safety.confirm import ConfirmationChannel, ConfirmationManager
from localguardian.safety.policy import SafetyPolicy
from localguardian.tools.registry import ToolRegistry


def create_mcp_server(
    config: Optional[LocalGuardianConfig] = None,
    *,
    dry_run: bool = False,
):
    """Build and return a configured MCPServer (mcp 2.x) or FastMCP (mcp 1.x) instance."""
    try:
        from mcp.server.mcpserver import MCPServer as _ServerCls  # type: ignore
    except ImportError:
        from mcp.server.fastmcp import FastMCP as _ServerCls  # type: ignore

    cfg = config or load_config()
    if dry_run:
        cfg.safety.dry_run = True

    policy = SafetyPolicy(cfg)
    audit = AuditLogger(cfg.audit_db_path)
    confirm = ConfirmationManager(ConfirmationChannel.DIALOG)
    registry = ToolRegistry(cfg, policy, audit, confirm)

    mcp = _ServerCls("localguardian")

    @mcp.tool()
    def get_brightness() -> str:
        """Read current Windows display brightness percentage."""
        return registry.invoke("get_brightness", {}, route_tier="mcp").message

    @mcp.tool()
    def set_brightness(level: int) -> str:
        """Set Windows display brightness to an exact percentage (0-100)."""
        return registry.invoke("set_brightness", {"level": level}, route_tier="mcp").message

    @mcp.tool()
    def adjust_brightness(delta: int) -> str:
        """Increase or decrease display brightness by delta (-100 to +100)."""
        return registry.invoke("adjust_brightness", {"delta": delta}, route_tier="mcp").message

    @mcp.tool()
    def get_volume() -> str:
        """Read current Windows master volume and mute state."""
        return registry.invoke("get_volume", {}, route_tier="mcp").message

    @mcp.tool()
    def set_volume(level: int) -> str:
        """Set Windows master volume percentage (0-100)."""
        return registry.invoke("set_volume", {"level": level}, route_tier="mcp").message

    @mcp.tool()
    def adjust_volume(delta: int) -> str:
        """Increase or decrease Windows master volume by delta (-100 to +100)."""
        return registry.invoke("adjust_volume", {"delta": delta}, route_tier="mcp").message

    @mcp.tool()
    def toggle_mute(mute: Optional[bool] = None) -> str:
        """Mute (true), unmute (false), or toggle (null) Windows audio."""
        return registry.invoke("toggle_mute", {"mute": mute}, route_tier="mcp").message

    @mcp.tool()
    def media_control(action: str) -> str:
        """Control media playback: play_pause, next, or previous."""
        return registry.invoke("media_control", {"action": action}, route_tier="mcp").message

    @mcp.tool()
    def open_app(app_name: str) -> str:
        """Launch an allowlisted desktop application (chrome, notepad, calculator, paint, edge, vscode)."""
        return registry.invoke("open_app", {"app_name": app_name}, route_tier="mcp").message

    @mcp.tool()
    def chrome_search(query: str) -> str:
        """Open Google Chrome (priority #1 browser) and search Google for query."""
        return registry.invoke("chrome_search", {"query": query}, route_tier="mcp").message

    @mcp.tool()
    def chrome_open_url(url: str) -> str:
        """Open a safe http:// or https:// URL in Google Chrome (priority #1 browser)."""
        return registry.invoke("chrome_open_url", {"url": url}, route_tier="mcp").message

    @mcp.tool()
    def list_open_windows() -> str:
        """List currently visible desktop windows (read-only)."""
        return registry.invoke("list_open_windows", {}, route_tier="mcp").message

    @mcp.tool()
    def focus_window(window_name: str) -> str:
        """Bring an open desktop window to the foreground."""
        return registry.invoke("focus_window", {"window_name": window_name}, route_tier="mcp").message

    @mcp.tool()
    def snap_window(window_name: str, position: str) -> str:
        """Snap an open window: left, right, maximize, or minimize."""
        return registry.invoke(
            "snap_window", {"window_name": window_name, "position": position}, route_tier="mcp"
        ).message

    @mcp.tool()
    def take_screenshot(filename: Optional[str] = None) -> str:
        """Save a PNG screenshot strictly inside ~/LocalGuardian_Workspace/screenshots/."""
        return registry.invoke("take_screenshot", {"filename": filename}, route_tier="mcp").message

    @mcp.tool()
    def activate_workspace_mode(mode: str) -> str:
        """Activate a safe workspace preset: coding, study, focus, or relax."""
        return registry.invoke("activate_workspace_mode", {"mode": mode}, route_tier="mcp").message

    @mcp.tool()
    def get_system_status() -> str:
        """Read-only check of brightness, volume, battery, CPU, RAM, and GPU."""
        return registry.invoke("get_system_status", {}, route_tier="mcp").message

    return mcp


def run_mcp_server(config: Optional[LocalGuardianConfig] = None, *, dry_run: bool = False) -> None:
    server = create_mcp_server(config, dry_run=dry_run)
    server.run(transport="stdio")
