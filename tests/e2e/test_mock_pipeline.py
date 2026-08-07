from __future__ import annotations

from dataclasses import replace

from openwrt_mcp.server import build_application


class FakeMCP:
    def __init__(self, _: str) -> None:
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


async def test_all_active_mcp_wrappers_delegate_to_kernel(settings) -> None:
    app = build_application(replace(settings, mock_mode=True), mcp_factory=FakeMCP)
    arguments = {
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
    try:
        for name, tool in app.mcp.tools.items():
            result = await tool(**arguments.get(name, {}))
            assert result.is_error is False, name
            assert result.structured_content is not None
            assert result.structured_content["success"] is True, name
    finally:
        await app.close()
