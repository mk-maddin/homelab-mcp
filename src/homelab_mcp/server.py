"""FastMCP application: read-only homelab health server.
Wires up the bearer-token auth middleware, registers all read-only tools,
and runs FastMCP's Streamable HTTP transport.
"""
from __future__ import annotations

import hmac
import logging

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from homelab_mcp import __version__, get_git_commit
from homelab_mcp.config import Settings, load_settings
from homelab_mcp.tools.containers import container_logs, list_containers
from homelab_mcp.tools.files import list_directory, read_file
from homelab_mcp.tools.network import network_connections, recent_journal_errors
from homelab_mcp.tools.osinfo import dmidecode_search, dpkg_packages, uname_info
from homelab_mcp.tools.shellcommands import (
    list_shell_commands,
    run_shell_command,
    tool_description as shell_command_tool_description,
)
from homelab_mcp.tools.services import list_services, service_status
from homelab_mcp.tools.system import disk_usage, system_status

logger = logging.getLogger("homelab_mcp")


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests that do not present the configured bearer token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not presented:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not hmac.compare_digest(presented, self._token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_mcp_server() -> FastMCP:
    """Construct the FastMCP instance and register all read-only tools."""
    mcp: FastMCP = FastMCP(
        name="homelab-mcp",
        instructions=(
            "Read-only inspection tools for a Linux home server. Use these "
            "to check system health, disk space, Docker containers, systemd "
            "services, journal errors, listening network ports, and permitted "
            "files or directories. Sensitive paths are blocked. No tool can "
            "modify state or accept arbitrary runtime commands. Optional "
            "administrator-defined commands are exposed only by fixed aliases; "
            "callers may only filter their output."
        ),
    )
    mcp.tool(system_status)
    mcp.tool(disk_usage)
    mcp.tool(list_containers)
    mcp.tool(container_logs)
    mcp.tool(list_services)
    mcp.tool(service_status)
    mcp.tool(recent_journal_errors)
    mcp.tool(network_connections)
    mcp.tool(read_file)
    mcp.tool(list_directory)
    mcp.tool(uname_info)
    mcp.tool(dpkg_packages)
    mcp.tool(dmidecode_search)
    mcp.tool(list_shell_commands)
    mcp.tool(run_shell_command, description=shell_command_tool_description())
    return mcp


def build_app(settings: Settings) -> Starlette:
    """Build the ASGI app: FastMCP Streamable HTTP wrapped with auth."""
    mcp = build_mcp_server()
    middleware = [Middleware(BearerTokenAuthMiddleware, token=settings.token)]
    return mcp.http_app(path="/mcp", middleware=middleware, transport="streamable-http")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    app = build_app(settings)
    import uvicorn

    from homelab_mcp.tools.files import (
        _DEFAULT_DENIED_FILES,
        _DEFAULT_DENIED_FOLDERS,
        _parse_denied_paths,
    )

    extra_files = _parse_denied_paths("HOMELAB_MCP_DENIED_FILES")
    extra_folders = _parse_denied_paths("HOMELAB_MCP_DENIED_FOLDERS")
    logger.info(
        "Denied paths: built-in files=%d, built-in folders=%d, env files=%d, env folders=%d",
        len(_DEFAULT_DENIED_FILES),len(_DEFAULT_DENIED_FOLDERS),len(extra_files),len(extra_folders),)

    from homelab_mcp.tools.shellcommands import available_shell_command_aliases
    shell_aliases = available_shell_command_aliases()
    logger.info(
        "Configured shell-command aliases (%d): %s",
        len(shell_aliases),
        ", ".join(shell_aliases) if shell_aliases else "none",
    )
    logger.info("homelab-mcp version=%s git-commit=%s", __version__, get_git_commit())
    logger.info("Starting homelab-mcp on %s:%d", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
