"""Runs the Airbnb MCP server (@openbnb/mcp-server-airbnb) and calls its search tool.

Airbnb's robots.txt forbids automated searches. The server respects it by default, so searches
are refused unless AIRBNB_IGNORE_ROBOTS_TXT=1 is set, which is the owner's decision to make.

From outside the US, www.airbnb.com answers with a page redirecting to the country's Airbnb, which the
server can't follow (its issue #60). Yori loads `mcp-servers/airbnb/install-domain-handoff.mjs` into
the server to follow it.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

SERVER = Path(__file__).resolve().parents[1] / "mcp-servers" / "airbnb" / "node_modules" / "@openbnb" / "mcp-server-airbnb" / "dist" / "index.js"
HANDOFF = Path(__file__).resolve().parents[1] / "mcp-servers" / "airbnb" / "install-domain-handoff.mjs"


class StaysUnavailable(Exception):
    """No stays could be fetched. `reason` is one short word, safe to show and log."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AirbnbMcpSource:
    def __init__(self, server_path: Path = SERVER, ignore_robots_txt: Optional[bool] = None, node: str = "node"):
        self.server_path = Path(server_path)
        if ignore_robots_txt is None:
            ignore_robots_txt = os.environ.get("AIRBNB_IGNORE_ROBOTS_TXT", "").strip() == "1"
        self.ignore_robots_txt = ignore_robots_txt
        self.node = node

    def server_args(self) -> list[str]:
        """`node` arguments: Yori's fix for Airbnb's country redirect page, then the server."""
        return ["--import", HANDOFF.as_uri(), str(self.server_path)] + (["--ignore-robots-txt"] if self.ignore_robots_txt else [])

    def search(self, arguments: dict) -> dict:
        if not self.server_path.exists():
            raise StaysUnavailable("not_installed")
        return asyncio.run(self._search(arguments))

    def listing_details(self, arguments: dict) -> dict:
        """One listing's details, including its map position (TP-07 A7)."""
        if not self.server_path.exists():
            raise StaysUnavailable("not_installed")
        return asyncio.run(self._search(arguments, tool="airbnb_listing_details"))

    async def _search(self, arguments: dict, tool: str = "airbnb_search") -> dict:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async with stdio_client(StdioServerParameters(command=self.node, args=self.server_args())) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)

        text = "".join(getattr(part, "text", "") or "" for part in result.content)
        try:
            data = json.loads(text)
        except ValueError:
            raise StaysUnavailable("failed") from None
        failed = getattr(result, "is_error", None) or getattr(result, "isError", None) or "error" in data
        if failed:
            raise StaysUnavailable("blocked_by_robots_txt" if "robots.txt" in str(data.get("error", "")) else "failed")
        return data
