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

    Uses a single shared event loop for all async calls so that
    persistent connections (SSH, etc.) work across multiple invocations.
    """

    def __init__(self, mcp: Any) -> None:
        self._mcp = mcp
        self._tools: dict[str, Any] = self._discover_tools()
        self._loop: asyncio.AbstractEventLoop | None = None

    def _discover_tools(self) -> dict[str, Any]:
        """Probe known tool storage locations.

        Probes 4 locations in priority order to remain compatible across
        FastMCP 2.x and 3.x: _tool_manager._tools → _tools → tools →
        list_tools() async fallback.
        """
        # 1. FastMCP 2.x primary
        if hasattr(self._mcp, "_tool_manager") and hasattr(self._mcp._tool_manager, "_tools"):
            return dict(self._mcp._tool_manager._tools)
        # 2. FastMCP 2.x alternate
        if hasattr(self._mcp, "_tools"):
            return dict(self._mcp._tools)
        # 3. FastMCP 2.x legacy
        if hasattr(self._mcp, "tools"):
            val = self._mcp.tools
            if isinstance(val, dict):
                return dict(val)
        # 4. FastMCP 3.x: async list_tools()
        list_tools_method = getattr(self._mcp, "list_tools", None)
        if list_tools_method is not None:
            loop = asyncio.new_event_loop()
            try:
                tools_result: list[Any] = loop.run_until_complete(list_tools_method())
                result: dict[str, Any] = {}
                for t in tools_result:
                    name = getattr(t, "name", None)
                    if name:
                        result[name] = t
                return result
            except Exception:
                pass
            finally:
                loop.close()
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
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
            loop = self._loop
            try:
                result = loop.run_until_complete(fn(**kwargs))
            finally:
                pass
        else:
            result = fn(**kwargs)

        if isinstance(result, str):
            return result
        return json.dumps({"success": True, "data": result})
