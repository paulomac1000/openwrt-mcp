"""Official MCP SDK v2 in-memory client acceptance tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

mcp = pytest.importorskip("mcp", reason="official MCP SDK unavailable in restricted local env")
from mcp import Client  # type: ignore[attr-defined]  # noqa: E402

from openwrt_mcp.server import build_application  # noqa: E402


@pytest.mark.integration
async def test_official_client_lists_and_invokes_active_tools(settings):
    app = build_application(replace(settings, mock_mode=True))
    try:
        async with Client(app.mcp) as client:
            listing = await client.list_tools()
            names = {tool.name for tool in listing.tools}
            assert len(names) == 19
            assert "get_router_info" in names
            assert "uci_set" not in names

            result = await client.call_tool("get_router_info", {})
            assert result.structured_content is not None
            assert result.structured_content["success"] is True
            assert result.structured_content["data"]["hostname"] == "mock-router"
    finally:
        await app.close()
