"""End-to-end tests: full pipeline from REST API to tool execution."""

import os
import socket

import pytest
import requests

REST_PORT = int(os.getenv("REST_API_PORT", "9096"))
BASE_URL = f"http://127.0.0.1:{REST_PORT}"


def _server_running():
    try:
        s = socket.create_connection(("127.0.0.1", REST_PORT), timeout=1)
        s.close()
        return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _server_running(), reason="MCP server not running"),
]

NO_ARG_TOOLS = [
    "get_router_info",
    "get_router_wifi_status",
    "get_router_dhcp_leases",
    "get_router_firewall_rules",
    "list_router_packages",
    "diagnose_router_connectivity",
    "get_dhcp_static_leases",
]


class TestFullPipeline:
    """Test the full pipeline from health check to tool execution."""

    def test_health_to_tools_flow(self):
        """Full flow: health → tools list → call first tool."""
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        assert r.status_code == 200

        r = requests.get(f"{BASE_URL}/api/tools", timeout=5)
        tools = r.json()["tools"]
        assert len(tools) == 13

        first_tool = tools[0]["name"]
        r = requests.post(
            f"{BASE_URL}/api/tools/{first_tool}",
            json={},
            timeout=10,
        )
        data = r.json()
        assert "success" in data

    @pytest.mark.parametrize("tool_name", NO_ARG_TOOLS)
    def test_tool_returns_success_field(self, tool_name):
        """Every no-arg tool returns a 'success' field."""
        r = requests.post(
            f"{BASE_URL}/api/tools/{tool_name}",
            json={},
            timeout=10,
        )
        data = r.json()
        assert "success" in data, f"Tool '{tool_name}' response missing 'success' field"

    def test_uci_config_with_param(self):
        """Tool with parameter — read_router_uci_config."""
        r = requests.post(
            f"{BASE_URL}/api/tools/read_router_uci_config",
            json={"config_name": "dhcp"},
            timeout=10,
        )
        data = r.json()
        assert "success" in data
