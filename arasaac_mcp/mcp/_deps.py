"""The MCP dependencies (fastmcp, the MCP SDK, Starlette).

One import point so the server modules do not each repeat the same imports.
These are regular dependencies of the ``arasaac-mcp`` package.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image as McpImage
from mcp.types import TextContent
from starlette.responses import Response

__all__ = ["FastMCP", "ToolResult", "McpImage", "TextContent", "Response"]
