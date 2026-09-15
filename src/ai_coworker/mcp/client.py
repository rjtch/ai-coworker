"""MCP client wiring — tools for the chat agent (currently none)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from ai_coworker.config import Settings

logger = logging.getLogger(__name__)


def _http_server(url: str, token: str | None, name: str) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return {
        "transport": "streamable_http",
        "url": url,
        "headers": headers,
        "name": name,
    }


def mcp_server_configs(settings: Settings) -> dict[str, dict[str, Any]]:
    """Remote MCP servers from env. Empty dict = no remote tools (dev-friendly)."""
    servers: dict[str, dict[str, Any]] = {}
    if settings.mcp_github_url:
        servers["github"] = _http_server(
            settings.mcp_github_url, settings.mcp_github_token, "github"
        )
    if settings.mcp_ci_url:
        servers["ci"] = _http_server(settings.mcp_ci_url, settings.mcp_ci_token, "ci")
    return servers


ROLE_MCP_ALLOWLIST: dict[str, set[str]] = {
    "chat": set(),
}


async def load_tools_for_role(role: str, settings: Settings) -> list[BaseTool]:
    """Load MCP tools filtered by role. Returns [] if no servers or adapter unavailable."""
    allow = ROLE_MCP_ALLOWLIST.get(role, set())
    all_servers = mcp_server_configs(settings)
    selected = {k: v for k, v in all_servers.items() if k in allow}
    if not selected:
        return []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("langchain-mcp-adapters not installed; running without MCP tools")
        return []

    client = MultiServerMCPClient(selected)
    tools = await client.get_tools()
    logger.info("Loaded %d MCP tools for role=%s servers=%s", len(tools), role, list(selected))
    return tools
