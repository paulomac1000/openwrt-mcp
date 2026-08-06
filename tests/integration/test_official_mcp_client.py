"""Official MCP SDK v2 in-memory acceptance tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

pytest.importorskip("mcp", reason="official MCP SDK unavailable locally")
from mcp import Client  # type: ignore[attr-defined]  # noqa: E402

from openwrt_mcp.mock_explorer import MockOpenWRTExplorer  # noqa: E402
from openwrt_mcp.server import build_application  # noqa: E402


@pytest.mark.integration
async def test_official_client_lists_and_invokes_active_tools(settings: Any) -> None:
    app = build_application(replace(settings, mock_mode=True))
    async with Client(app.mcp) as client:
        listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        assert len(names) == 19
        assert "get_router_info" in names
        assert "uci_set" not in names

        result = await client.call_tool("get_router_info", {})
        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["success"] is True
        assert result.structured_content["data"]["hostname"] == "mock-router"


class FailingExplorer(MockOpenWRTExplorer):
    async def get_system_info(self) -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": "UPSTREAM_FAILURE",
                "message": "password=router-secret",
                "retryable": False,
            },
        }


@pytest.mark.integration
async def test_official_client_receives_sanitized_tool_error(settings: Any) -> None:
    app = build_application(
        replace(settings, mock_mode=True),
        explorer_factory=FailingExplorer,
    )
    async with Client(app.mcp) as client:
        result = await client.call_tool("get_router_info", {})
        assert result.is_error is True
        assert result.structured_content is None
        rendered = "\n".join(
            str(getattr(block, "text", "")) for block in result.content
        )
        assert "router-secret" not in rendered
        assert "<REDACTED>" in rendered


class SlowExplorer(MockOpenWRTExplorer):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def get_system_info(self) -> dict[str, Any]:
        self.entered.set()
        try:
            await asyncio.sleep(60)
        finally:
            self.cancelled.set()
        return await super().get_system_info()


@pytest.mark.integration
async def test_official_client_timeout_is_a_tool_error(settings: Any) -> None:
    explorer = SlowExplorer()
    app = build_application(
        replace(settings, mock_mode=True),
        explorer_factory=lambda: explorer,
    )
    manifest = app.kernel.registry.get("get_router_info")
    app.kernel.registry._manifests["get_router_info"] = replace(  # noqa: SLF001
        manifest,
        timeout_ms=20,
    )
    async with Client(app.mcp) as client:
        result = await client.call_tool("get_router_info", {})
        assert result.is_error is True
        assert explorer.cancelled.is_set()
        rendered = "\n".join(
            str(getattr(block, "text", "")) for block in result.content
        )
        assert "TIMEOUT" in rendered


@pytest.mark.integration
async def test_official_client_cancellation_releases_target_lock(
    settings: Any,
) -> None:
    explorer = SlowExplorer()
    app = build_application(
        replace(settings, mock_mode=True),
        explorer_factory=lambda: explorer,
    )
    async with Client(app.mcp) as client:
        task = asyncio.create_task(client.call_tool("get_router_info", {}))
        await asyncio.wait_for(explorer.entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(explorer.cancelled.wait(), timeout=1)

        follow_up = await asyncio.wait_for(
            client.call_tool("test_router_connection", {}),
            timeout=1,
        )
        assert follow_up.is_error is False
