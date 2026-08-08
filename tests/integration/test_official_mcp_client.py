"""Official MCP SDK 2.0.0 in-memory acceptance tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import mcp
import pytest

if getattr(mcp, "__test_fake__", False):
    pytest.skip("official MCP SDK unavailable locally", allow_module_level=True)

from mcp import Client  # type: ignore[attr-defined]  # noqa: E402

from openwrt_mcp.mock_explorer import MockOpenWRTExplorer  # noqa: E402
from openwrt_mcp.server import build_application  # noqa: E402


@pytest.mark.integration
async def test_official_client_lists_exact_closed_schemas_and_invokes_tools(
    settings: Any,
) -> None:
    app = build_application(replace(settings, mock_mode=True))
    async with Client(app.mcp) as client:
        listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        assert len(names) == 19
        assert "get_router_info" in names
        assert "uci_set" not in names
        assert all(tool.input_schema.get("additionalProperties") is False for tool in listing.tools)
        ping = next(tool for tool in listing.tools if tool.name == "ping_host")
        expected = app.kernel.registry.get("ping_host").input_schema.as_json_schema()
        assert ping.input_schema == expected
        assert ping.input_schema["properties"]["count"]["maximum"] == 5

        result = await client.call_tool("get_router_info", {})
        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["data"]["hostname"] == "mock-router"


@pytest.mark.integration
async def test_official_client_rejects_unknown_and_missing_arguments(settings: Any) -> None:
    app = build_application(replace(settings, mock_mode=True))
    async with Client(app.mcp) as client:
        missing = await client.call_tool("ping_host", {})
        unknown = await client.call_tool(
            "ping_host",
            {"host": "example.com", "unknown": "ignored"},
        )
        assert missing.is_error is True
        assert unknown.is_error is True


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
async def test_official_client_receives_sanitized_structured_tool_error(
    settings: Any,
) -> None:
    app = build_application(replace(settings, mock_mode=True), explorer_factory=FailingExplorer)
    async with Client(app.mcp) as client:
        result = await client.call_tool("get_router_info", {})
        rendered = "\n".join(str(getattr(block, "text", "")) for block in result.content)
        assert result.is_error is True
        assert result.structured_content is not None
        assert result.structured_content["success"] is False
        assert result.structured_content["error"]["code"] == "UPSTREAM_FAILURE"
        assert "router-secret" not in rendered
        assert "router-secret" not in str(result.structured_content)
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
async def test_official_client_timeout_releases_lock(settings: Any) -> None:
    explorer = SlowExplorer()
    app = build_application(replace(settings, mock_mode=True), explorer_factory=lambda: explorer)
    manifest = app.kernel.registry.get("get_router_info")
    app.kernel.registry._manifests["get_router_info"] = replace(  # noqa: SLF001
        manifest,
        timeout_ms=20,
    )
    async with Client(app.mcp) as client:
        timed_out = await client.call_tool("get_router_info", {})
        assert timed_out.is_error is True
        assert timed_out.structured_content is not None
        assert timed_out.structured_content["error"]["code"] == "TIMEOUT"
        assert explorer.cancelled.is_set()
        follow_up = await asyncio.wait_for(
            client.call_tool("test_router_connection", {}),
            timeout=1,
        )
        assert follow_up.is_error is False


@pytest.mark.integration
async def test_official_client_task_cancellation_releases_lock(settings: Any) -> None:
    explorer = SlowExplorer()
    app = build_application(replace(settings, mock_mode=True), explorer_factory=lambda: explorer)
    async with Client(app.mcp) as client:
        task = asyncio.create_task(client.call_tool("get_router_info", {}))
        await explorer.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert explorer.cancelled.is_set()
        follow_up = await asyncio.wait_for(
            client.call_tool("test_router_connection", {}),
            timeout=1,
        )
        assert follow_up.is_error is False
