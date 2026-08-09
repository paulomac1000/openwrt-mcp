#!/usr/bin/env python3
"""Smoke an installed wheel through real official MCP stdio subprocesses."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from collections.abc import Mapping
from typing import Any, TextIO

from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_MODERN_PROTOCOL = "2026-07-28"
_LEGACY_PROTOCOL = "2025-11-25"
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
    executable = shutil.which("openwrt-mcp")
    if executable is None:
        raise RuntimeError("installed openwrt-mcp console entry point was not found")
    env = {key: value for key in _ALLOWED_CHILD_ENV if (value := os.environ.get(key)) is not None}
    env.update(
        {
            "OPENWRT_MOCK_MODE": "1",
            "MCP_TRANSPORT": "stdio",
            "HEALTH_ENABLED": "0",
            "LOG_LEVEL": "WARNING",
        }
    )
    return StdioServerParameters(command=executable, args=[], env=env)


def _assert_catalog_and_result(listing: Any, result: Any) -> None:
    tools = {tool.name: tool for tool in listing.tools}
    names = set(tools)
    if len(names) != 19 or "uci_set" in names or "get_router_info" not in names:
        raise RuntimeError(f"unexpected active catalog: {sorted(names)}")
    if any(tool.input_schema.get("additionalProperties") is not False for tool in tools.values()):
        raise RuntimeError("one or more public MCP input schemas are not closed")
    ping_schema = tools["ping_host"].input_schema
    count_schema = ping_schema.get("properties", {}).get("count", {})
    if count_schema.get("maximum") != 5 or count_schema.get("minimum") != 1:
        raise RuntimeError(f"ping_host schema lost kernel bounds: {ping_schema}")

    structured = result.structured_content or {}
    if result.is_error or structured.get("success") is not True:
        raise RuntimeError(f"unexpected get_router_info result: {structured}")
    data = structured.get("data")
    if not isinstance(data, Mapping) or data.get("hostname") != "mock-router":
        raise RuntimeError(f"unexpected get_router_info data: {data}")


def _assert_invalid_host_error(result: Any) -> None:
    structured = result.structured_content or {}
    error = structured.get("error") if isinstance(structured, Mapping) else None
    if not result.is_error or not isinstance(error, Mapping):
        raise RuntimeError(f"invalid host did not return a structured tool error: {structured}")
    if error.get("code") != "INVALID_PARAM":
        raise RuntimeError(f"unexpected invalid-host error: {structured}")


def _assert_clean_stderr(errlog: TextIO, *, mode: str) -> None:
    errlog.flush()
    errlog.seek(0)
    rendered = errlog.read()
    if "Traceback (most recent call last)" in rendered:
        raise RuntimeError(f"{mode} stdio child emitted a traceback: {rendered[-2000:]}")


async def _smoke_modern_stdio() -> None:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
        transport = stdio_client(
            _server_params(),
            errlog=errlog,
        )
        async with Client(transport) as client:
            if str(client.protocol_version) != _MODERN_PROTOCOL:
                raise RuntimeError(
                    f"modern client negotiated {client.protocol_version}, "
                    f"expected {_MODERN_PROTOCOL}"
                )
            listing = await client.list_tools()
            result = await client.call_tool("get_router_info", {})
            invalid = await client.call_tool("ping_host", {"host": "bad;reboot"})
            _assert_catalog_and_result(listing, result)
            _assert_invalid_host_error(invalid)
        _assert_clean_stderr(errlog, mode="modern")


async def _smoke_legacy_stdio() -> None:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
        async with stdio_client(
            _server_params(),
            errlog=errlog,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                if str(initialized.protocol_version) != _LEGACY_PROTOCOL:
                    raise RuntimeError(
                        f"legacy client negotiated {initialized.protocol_version}, "
                        f"expected {_LEGACY_PROTOCOL}"
                    )
                listing = await session.list_tools()
                result = await session.call_tool("get_router_info", {})
                invalid = await session.call_tool("ping_host", {"host": "bad;reboot"})
                _assert_catalog_and_result(listing, result)
                _assert_invalid_host_error(invalid)
        _assert_clean_stderr(errlog, mode="legacy")


async def _run() -> None:
    await asyncio.wait_for(_smoke_modern_stdio(), timeout=30)
    await asyncio.wait_for(_smoke_legacy_stdio(), timeout=30)


def main() -> int:
    asyncio.run(_run())
    print("official MCP stdio artifact smoke passed (modern + legacy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
