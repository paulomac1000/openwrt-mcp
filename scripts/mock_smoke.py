#!/usr/bin/env python3
"""Run every active capability against deterministic mock router data."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from openwrt_mcp.server import build_application
from openwrt_mcp.settings import load_settings


class SmokeMCP:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[fn.__name__] = fn
            return fn
        return decorator


_ARGUMENTS: dict[str, dict[str, Any]] = {
    "read_router_uci_config": {"config_name": "network"},
    "get_router_logs": {"lines": 20, "filter_level": "all"},
    "search_router_logs": {"search_term": "dnsmasq", "max_results": 5},
    "search_dhcp_logs": {"search_term": "mock-client"},
    "get_device_dhcp_details": {"ip_address": "192.0.2.101"},
    "ping_host": {"host": "192.0.2.1", "count": 2},
    "traceroute_host": {"host": "192.0.2.1"},
    "nslookup_host": {"host": "example.test", "dns_server": "192.0.2.53"},
    "wifi_scan": {"radio": "wlan0"},
}


async def main() -> int:
    os.environ["OPENWRT_MOCK_MODE"] = "1"
    os.environ["MCP_TRANSPORT"] = "stdio"
    app = build_application(load_settings(force=True), mcp_factory=SmokeMCP)
    failures: list[str] = []
    for name in app.kernel.registry.active_names():
        result = await app.kernel.invoke(name, _ARGUMENTS.get(name, {}))
        if not result.success:
            failures.append(f"{name}: {result.as_dict()}")
    await app.close()
    if failures:
        print("\n".join(failures))
        return 1
    print(f"mock smoke passed: {len(app.kernel.registry.active())} active capabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
