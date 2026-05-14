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
    "get_router_context",
    "describe_router_capabilities",
    "test_router_connection",
]


class TestFullPipeline:
    """Test the full pipeline from health check to tool execution."""

    def test_health_to_tools_flow(self):
        """Full flow: health → tools list → call first tool."""
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        assert r.status_code == 200

        r = requests.get(f"{BASE_URL}/api/tools", timeout=5)
        tools = r.json()["tools"]
        assert len(tools) == 24

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

    # ── Parametric tool response structure validation ─────────────────

    PARAM_TOOLS_WITH_STRUCTURE = [
        ("ping_host", {"host": "8.8.8.8", "count": 2}, ["host"]),
        ("nslookup_host", {"host": "google.com"}, ["host"]),
        ("wifi_scan", {"radio": "wlan0"}, ["radio"]),
    ]

    @pytest.mark.parametrize("tool_name,kwargs,expected_keys", PARAM_TOOLS_WITH_STRUCTURE)
    def test_tool_returns_expected_keys(self, tool_name, kwargs, expected_keys):
        """Parametric tools should return response containing expected keys."""
        r = requests.post(f"{BASE_URL}/api/tools/{tool_name}", json=kwargs, timeout=10)
        data = r.json()
        assert "success" in data, f"Tool '{tool_name}' missing 'success' field"
        if data.get("success"):
            d = data.get("result", {}).get("data", {})
            if d:
                for key in expected_keys:
                    assert key in d, f"Tool '{tool_name}' response missing key '{key}'"

    def test_traceroute_via_rest(self):
        """Traceroute is slow — separate test with longer timeout."""
        r = requests.post(
            f"{BASE_URL}/api/tools/traceroute_host",
            json={"host": "8.8.8.8"},
            timeout=60,
        )
        data = r.json()
        assert "success" in data
        if data.get("success"):
            d = data.get("result", {}).get("data", {})
            assert d.get("host") == "8.8.8.8"


class TestWriteToolsE2E:
    """Safe write tool E2E tests — idempotent, zero config changes."""

    def test_uci_set_hostname_idempotent(self):
        """Set hostname to current value (idempotent — no change)."""
        r_read = requests.post(
            f"{BASE_URL}/api/tools/read_router_uci_config",
            json={"config_name": "system"},
            timeout=10,
        )
        hostname = "OpenWrt"
        data_read = r_read.json()
        if data_read.get("success"):
            d = data_read.get("result", {}).get("data", {})
            if d.get("success"):
                for key, val in d.get("sample", {}).items():
                    if "hostname" in key:
                        hostname = val
                        break

        r_write = requests.post(
            f"{BASE_URL}/api/tools/uci_set",
            json={
                "config": "system",
                "section": "@system[0]",
                "option": "hostname",
                "value": str(hostname),
            },
            timeout=10,
        )
        data = r_write.json()
        assert data["success"] is True, f"uci_set failed: {data.get('error')}"
        d = data.get("result", {}).get("data", {})
        assert d.get("action") == "uci_set"
        assert d.get("config") == "system"
        assert d.get("option") == "hostname"

    def test_uci_commit_noop(self):
        """Commit system config with no pending changes — safe no-op."""
        r = requests.post(
            f"{BASE_URL}/api/tools/uci_commit",
            json={"config": "system"},
            timeout=10,
        )
        data = r.json()
        assert data["success"] is True, f"uci_commit failed: {data.get('error')}"
        d = data.get("result", {}).get("data", {})
        assert d.get("action") == "uci_committed"
        assert d.get("config") == "system"
