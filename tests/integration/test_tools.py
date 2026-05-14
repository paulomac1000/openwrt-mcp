"""Integration tests: per-tool verification via MCPWrapper (Canonical Template 10)."""

import json
import os

import pytest
from fastmcp import FastMCP

from openwrt_mcp.tools.registration import register_openwrt_tools
from tests.integration.mcp_wrapper import MCPWrapper

pytestmark = pytest.mark.integration

if not os.getenv("OPENWRT_HOST"):
    pytest.skip("Integration tests require OPENWRT_HOST", allow_module_level=True)

_HOST = os.getenv("OPENWRT_HOST", "")
if _HOST in ("192.168.1.1", "YOUR_ROUTER_IP", "CHANGEME"):
    pytest.skip(
        f"OPENWRT_HOST is set to placeholder value '{_HOST}'",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def mcp_wrapper():
    """Create an in-process MCP instance via MCPWrapper."""
    mcp = FastMCP("OpenWRT-Integration-Test")
    register_openwrt_tools(mcp)
    return MCPWrapper(mcp)


NO_ARG_TOOLS = [
    "test_router_connection",
    "get_router_info",
    "get_router_wifi_status",
    "get_router_dhcp_leases",
    "get_router_firewall_rules",
    "list_router_packages",
    "get_dhcp_static_leases",
    "get_router_context",
    "describe_router_capabilities",
    "reload_network",
    "diagnose_router_connectivity",
]


class TestNoArgTools:
    """Integration tests for tools with no required arguments."""

    @pytest.mark.parametrize("tool_name", NO_ARG_TOOLS)
    def test_no_arg_tool_returns_success_field(self, mcp_wrapper, tool_name):
        """Every no-arg tool must return a JSON response with a 'success' field."""
        result = mcp_wrapper.call_tool(tool_name)
        data = json.loads(result)
        assert "success" in data, f"Tool '{tool_name}' response missing 'success' field"


class TestParameterizedTools:
    """Integration tests for tools that accept parameters."""

    @pytest.mark.parametrize(
        "tool_name, kwargs",
        [
            ("read_router_uci_config", {"config_name": "dhcp"}),
            ("get_router_logs", {"lines": 10, "filter_level": "all"}),
            ("search_router_logs", {"search_term": "dhcp", "max_results": 5}),
            ("search_dhcp_logs", {"search_term": "aa:bb:cc:dd:ee:ff"}),
            ("get_device_dhcp_details", {"mac_address": "aa:bb:cc:dd:ee:ff"}),
            ("get_device_dhcp_details", {"ip_address": "192.168.1.100"}),
            ("restart_interface", {"interface_name": "wan"}),
            ("restart_interface", {"interface_name": "lo"}),
            (
                "uci_set",
                {"config": "network", "section": "wan", "option": "ipaddr", "value": "10.0.0.1"},
            ),
            ("uci_commit", {"config": "network"}),
            ("ping_host", {"host": "8.8.8.8", "count": 2}),
            ("traceroute_host", {"host": "8.8.8.8"}),
            ("nslookup_host", {"host": "google.com"}),
            ("wifi_scan", {"radio": "wlan0"}),
        ],
    )
    def test_tool_with_params_returns_success_field(self, mcp_wrapper, tool_name, kwargs):
        """Parameterized tools should return JSON with 'success' field."""
        result = mcp_wrapper.call_tool(tool_name, **kwargs)
        data = json.loads(result)
        assert "success" in data, f"Tool '{tool_name}' with {kwargs} missing 'success' field"

    @pytest.mark.parametrize(
        "tool_name, kwargs",
        [
            ("read_router_uci_config", {"config_name": "nonexistent_config"}),
            ("search_router_logs", {"search_term": "; rm -rf /"}),
            ("search_dhcp_logs", {"search_term": "; rm -rf /"}),
        ],
    )
    def test_tool_with_invalid_args_returns_error(self, mcp_wrapper, tool_name, kwargs):
        """Invalid arguments should return success: false with structured error."""
        result = mcp_wrapper.call_tool(tool_name, **kwargs)
        data = json.loads(result)
        assert data["success"] is False, (
            f"Tool '{tool_name}' with {kwargs} should return success: false"
        )
        assert "error" in data, f"Error response missing 'error' field for '{tool_name}'"
