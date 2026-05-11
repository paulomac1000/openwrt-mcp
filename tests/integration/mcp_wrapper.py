"""MCPWrapper — abstracts FastMCP internals for integration tests.

Canonical Template 8 from mcp_standards.md.
"""

import asyncio
import inspect
import json
from typing import Any


class MCPWrapper:
    """Wraps a FastMCP instance for integration testing.

    Probes multiple internal storage locations and callable attributes
    to remain compatible across FastMCP version upgrades.
    """

    def __init__(self, mcp: Any) -> None:
        self._mcp = mcp
        self._tools: dict[str, Any] = self._discover_tools()

    def _discover_tools(self) -> dict[str, Any]:
        """Probe known tool storage locations."""
        if hasattr(self._mcp, "_tool_manager") and hasattr(self._mcp._tool_manager, "_tools"):
            return dict(self._mcp._tool_manager._tools)
        if hasattr(self._mcp, "_tools"):
            return dict(self._mcp._tools)
        if hasattr(self._mcp, "tools"):
            val = self._mcp.tools
            if isinstance(val, dict):
                return dict(val)
        return {}

    def _unwrap_tool(self, tool: Any) -> Any:
        """Extract the callable from a Tool wrapper object."""
        for attr in ("fn", "func", "_func", "function"):
            if hasattr(tool, attr):
                return getattr(tool, attr)
        return tool

    def get_tool(self, name: str) -> Any | None:
        """Return the raw tool object by name."""
        return self._tools.get(name)

    def call_tool(self, tool_name: str, **kwargs: Any) -> str:
        """Call a tool by name with keyword arguments.

        Returns the JSON string response from the tool.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return json.dumps({"success": False, "error": f"Tool '{tool_name}' not found"})

        fn = self._unwrap_tool(tool)

        if inspect.iscoroutinefunction(fn):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(fn(**kwargs))
            finally:
                loop.close()
        else:
            result = fn(**kwargs)

        if isinstance(result, str):
            return result
        return json.dumps({"success": True, "data": result})
