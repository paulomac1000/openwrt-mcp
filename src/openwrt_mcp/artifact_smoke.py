#!/usr/bin/env python3
"""Smoke an installed wheel with the official MCP SDK v2 client."""

from __future__ import annotations

import asyncio
import os

from mcp import Client

from openwrt_mcp.server import build_application
from openwrt_mcp.settings import load_settings


async def main() -> int:
    os.environ["OPENWRT_MOCK_MODE"] = "1"
    os.environ["MCP_TRANSPORT"] = "stdio"
    app = build_application(load_settings(force=True))
    try:
        async with Client(app.mcp) as client:
            listing = await client.list_tools()
            names = {tool.name for tool in listing.tools}
            if len(names) != 19 or "uci_set" in names:
                raise RuntimeError(f"unexpected active catalog: {sorted(names)}")
            result = await client.call_tool("get_router_info", {})
            structured = result.structured_content or {}
            if structured.get("success") is not True:
                raise RuntimeError(f"unexpected result: {structured}")
        print("official MCP client artifact smoke passed")
        return 0
    finally:
        await app.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
