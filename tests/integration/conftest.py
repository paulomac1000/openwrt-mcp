"""Integration test fixtures — shared conftest for MCP tool registration.

All integration test files register tools via register_openwrt_tools(mcp).
When adding a new tool module, it must be registered here as well.
Current registration modules:
  - src/openwrt_mcp/tools/registration.py  (all 24 tools, single function)

Each integration test file creates its own FastMCP instance and calls
register_openwrt_tools(mcp) in its module-scoped fixture. There is no
shared fixture across integration files — each file is self-contained.
"""
