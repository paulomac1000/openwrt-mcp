#!/usr/bin/env python3
"""Smoke an installed wheel through real official MCP stdio subprocesses."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import tempfile
from collections.abc import Mapping
from typing import Any, TextIO

from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_MODERN_PROTOCOL = "2026-07-28"
_LEGACY_PROTOCOL = "2025-11-25"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_params(*, health_port: int) -> StdioServerParameters:
    executable = shutil.which("openwrt-mcp")
    if executable is None:
        raise RuntimeError("installed openwrt-mcp console entry point was not found")
    env = dict(os.environ)
    env.update(
        {
            "OPENWRT_MOCK_MODE": "1",
            "MCP_TRANSPORT": "stdio",
            "HEALTH_PORT": str(health_port),
            "LOG_LEVEL": "WARNING",
        }
    )
    return StdioServerParameters(command=executable, args=[], env=env)


def _assert_catalog_and_result(listing: Any, result: Any) -> None:
    names = {tool.name for tool in listing.tools}
    if len(names) != 19 or "uci_set" in names or "get_router_info" not in names:
        raise RuntimeError(f"unexpected active catalog: {sorted(names)}")
    structured = result.structured_content or {}
    if result.is_error or structured.get("success") is not True:
        raise RuntimeError(f"unexpected get_router_info result: {structured}")
    data = structured.get("data")
    if not isinstance(data, Mapping) or data.get("hostname") != "mock-router":
        raise RuntimeError(f"unexpected get_router_info data: {data}")


def _assert_clean_stderr(errlog: TextIO, *, mode: str) -> None:
    errlog.flush()
    errlog.seek(0)
    rendered = errlog.read()
    if "Traceback (most recent call last)" in rendered:
        raise RuntimeError(f"{mode} stdio child emitted a traceback: {rendered[-2000:]}")


async def _smoke_modern_stdio() -> None:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
        transport = stdio_client(
            _server_params(health_port=_free_loopback_port()),
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
            _assert_catalog_and_result(listing, result)
        _assert_clean_stderr(errlog, mode="modern")


async def _smoke_legacy_stdio() -> None:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
        async with stdio_client(
            _server_params(health_port=_free_loopback_port()),
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
                _assert_catalog_and_result(listing, result)
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
