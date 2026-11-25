"""End-to-end smoke: real stdio subprocess speaking the official MCP protocol.

This fills the smoke layer of the migration: the server binary is spawned as a
real child process over stdio and driven through the official MCP client, so
registration, transport framing, and kernel invocation are proven together
without a router. The same shape runs in provider CI against the exact wheel
and container via ``openwrt_mcp.artifact_smoke``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import mcp
import pytest

if getattr(mcp, "__test_fake__", False):
    pytest.skip("official MCP SDK unavailable locally", allow_module_level=True)

from mcp import Client, StdioServerParameters  # type: ignore[attr-defined]  # noqa: E402
from mcp.client.stdio import stdio_client  # type: ignore[attr-defined]  # noqa: E402

pytestmark = [pytest.mark.e2e]
_ALLOWED_CHILD_ENV = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "TEMP",
    "TMP",
    "TMPDIR",
)


def _server_params() -> StdioServerParameters:
    root = Path(__file__).resolve().parents[2]
    env = {key: value for key in _ALLOWED_CHILD_ENV if (value := os.environ.get(key)) is not None}
    env.update(
        {
            "PYTHONPATH": str(root / "src"),
            "OPENWRT_MOCK_MODE": "1",
            "MCP_TRANSPORT": "stdio",
            "HEALTH_ENABLED": "0",
            "LOG_LEVEL": "WARNING",
        }
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "openwrt_mcp"],
        env=env,
    )


def _assert_clean_stderr(errlog: tempfile._TemporaryFileWrapper[str]) -> None:
    errlog.flush()
    errlog.seek(0)
    rendered = errlog.read()
    assert "Traceback (most recent call last)" not in rendered


@pytest.mark.asyncio
async def test_stdio_subprocess_lists_closed_schemas_and_invokes_kernel() -> None:
    params = _server_params()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
        transport = stdio_client(params, errlog=errlog)
        async with Client(transport) as client:
            listing = await client.list_tools()
            names = {tool.name for tool in listing.tools}
            assert len(names) == 19
            assert "get_router_info" in names
            assert "uci_set" not in names
            assert all(
                tool.input_schema.get("additionalProperties") is False for tool in listing.tools
            )

            result = await client.call_tool("get_router_info", {})
            assert result.is_error is False
            structured = result.structured_content or {}
            data = structured.get("data", {})
            assert data.get("hostname") == "mock-router"
            assert data.get("openwrt_version") == "23.05-mock"
            assert data.get("partial") is False
        _assert_clean_stderr(errlog)


@pytest.mark.asyncio
async def test_stdio_subprocess_surfaces_sanitized_controlled_error() -> None:
    params = _server_params()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
        transport = stdio_client(params, errlog=errlog)
        async with Client(transport) as client:
            result = await client.call_tool(
                "read_router_uci_config",
                {"config_name": "not-allowed"},
            )
            assert result.is_error is True
            structured = result.structured_content or {}
            assert structured.get("success") is False
            assert "not supported" in str(structured.get("error", ""))
        _assert_clean_stderr(errlog)
