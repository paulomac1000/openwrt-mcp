"""Integration tests against a real OpenWRT router — READ-ONLY operations only.

SAFETY: ONLY READ TOOLS are tested here. Running write tools
(restart_interface, reload_network, reboot_device) against a real
router can cause permanent connectivity loss requiring physical reset.
Write tools are tested exclusively with mocks in
tests/integration/test_write_tools_mocked.py.

.env is loaded from conftest.py at the project root, before any test
module is imported. This ensures os.getenv() picks up the correct values.

Run:
  python3 -m pytest tests/integration/test_real_router.py -v --tb=long
"""

import json
import os
from pathlib import Path

import pytest
from fastmcp import FastMCP

from openwrt_mcp.observability import TOOLS_VERSION
from openwrt_mcp.tools.registration import register_openwrt_tools
from tests.integration.mcp_wrapper import MCPWrapper

pytestmark = pytest.mark.integration

if not os.getenv("OPENWRT_HOST"):
    pytest.skip("Real router tests require OPENWRT_HOST in .env", allow_module_level=True)

_HOST = os.getenv("OPENWRT_HOST", "")
if _HOST in ("192.168.1.1", "YOUR_ROUTER_IP", "CHANGEME"):
    pytest.skip(
        f"OPENWRT_HOST is set to placeholder value '{_HOST}'",
        allow_module_level=True,
    )

_ssh_key_path = os.getenv("OPENWRT_SSH_KEY", "/app/keys/openwrt_id_ed25519")
if not Path(_ssh_key_path).exists():
    pytest.skip(
        f"Real router tests require SSH key at {_ssh_key_path}",
        allow_module_level=True,
    )


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def mcp_client():
    """Create real MCP instance with all 24 tools registered."""
    mcp = FastMCP("OpenWRT-Real-Router-Test")
    register_openwrt_tools(mcp)
    return MCPWrapper(mcp)


def _parse(response: str) -> dict:
    """Parse JSON response and assert basic structure."""
    data = json.loads(response)
    assert "success" in data, f"Response missing 'success': {response[:200]}"
    return data


# ── SAFE READ-ONLY tests ───────────────────────────────────────────────────


class TestReadToolsResponseStructure:
    """Validate response structure from real router — no side effects."""

    def test_test_router_connection_connected(self, mcp_client):
        """Should report connected and return model/release info."""
        result = mcp_client.call_tool("test_router_connection")
        data = _parse(result)
        if data["success"] is True:
            d = data.get("data", {})
            assert d.get("status") == "connected"
            assert "model" in d
            assert "release" in d

    def test_get_router_info_has_keys(self, mcp_client):
        """Should return model, hostname, version, kernel, uptime, memory."""
        result = mcp_client.call_tool("get_router_info")
        data = _parse(result)
        d = data.get("data", {})
        assert d.get("model"), "Missing model"
        assert d.get("hostname"), "Missing hostname"
        assert d.get("openwrt_version"), "Missing openwrt_version"
        assert d.get("kernel"), "Missing kernel"
        assert d.get("uptime_seconds", 0) > 0, "Uptime should be > 0"
        assert d.get("memory_total_bytes", 0) > 0, "Memory should be > 0"

    def test_get_router_wifi_status_has_interfaces(self, mcp_client):
        """Should return interfaces list with SSID and mode."""
        result = mcp_client.call_tool("get_router_wifi_status")
        data = _parse(result)
        if data["success"] is True:
            ifaces = data.get("data", {}).get("interfaces", [])
            assert isinstance(ifaces, list)
            if ifaces:
                iface = ifaces[0]
                assert "ssid" in iface
                assert "mode" in iface
                assert "radio" in iface

    def test_get_router_dhcp_leases_has_leases(self, mcp_client):
        """Should return leases list with MAC, IP."""
        result = mcp_client.call_tool("get_router_dhcp_leases")
        data = _parse(result)
        if data["success"] is True:
            leases = data.get("data", {}).get("leases", [])
            assert isinstance(leases, list)
            if leases:
                lease = leases[0]
                assert "mac" in lease
                assert "ip" in lease

    def test_get_router_firewall_rules_has_type(self, mcp_client):
        """Should return firewall_type and rules_preview."""
        result = mcp_client.call_tool("get_router_firewall_rules")
        data = _parse(result)
        if data["success"] is True:
            assert "firewall_type" in data.get("data", {})

    def test_read_router_uci_config_dhcp(self, mcp_client):
        """Should return dhcp config entries."""
        result = mcp_client.call_tool("read_router_uci_config", config_name="dhcp")
        data = _parse(result)
        if data["success"] is True:
            d = data.get("data", {})
            assert d.get("config_name") == "dhcp"
            assert d.get("entries_count", 0) >= 0

    def test_list_router_packages_has_packages(self, mcp_client):
        """Should return packages list with name, version."""
        result = mcp_client.call_tool("list_router_packages")
        data = _parse(result)
        if data["success"] is True:
            d = data.get("data", {})
            assert d.get("packages_count", 0) > 0
            pkgs = d.get("packages_sample", [])
            if pkgs:
                assert "name" in pkgs[0]

    def test_get_router_logs_has_lines(self, mcp_client):
        """Should return logs text."""
        result = mcp_client.call_tool("get_router_logs", lines=10, filter_level="all")
        data = _parse(result)
        if data["success"] is True:
            assert data.get("data", {}).get("lines_count", 0) >= 0

    def test_diagnose_router_connectivity_has_summary(self, mcp_client):
        """Should return tests dict with health summary."""
        result = mcp_client.call_tool("diagnose_router_connectivity")
        data = _parse(result)
        if data["success"] is True:
            d = data.get("data", {})
            assert "tests" in d
            assert "summary" in d
            summary = d["summary"]
            assert "health" in summary
            assert "total" in summary

    def test_get_router_context_has_subsections(self, mcp_client):
        """Should return unified context with subsections."""
        result = mcp_client.call_tool("get_router_context")
        data = _parse(result)
        if data["success"] is True:
            d = data.get("data", {})
            assert "device_id" in d
            assert "subsections" in d
            assert d.get("schema_version") == "1.0"

    def test_describe_router_capabilities(self, mcp_client):
        """Should return server name, tools list, transports."""
        result = mcp_client.call_tool("describe_router_capabilities")
        data = _parse(result)
        d = data.get("data", {})
        assert d.get("server") == "OpenWRT-Observer"
        assert "tools" in d
        assert "transports" in d
        assert d.get("total_tools") == 24

    def test_ping_host_returns_reachable(self, mcp_client):
        """Should ping 8.8.8.8 and return reachable boolean."""
        result = mcp_client.call_tool("ping_host", host="8.8.8.8", count=2)
        data = _parse(result)
        d = data.get("data", {})
        assert d.get("host") == "8.8.8.8"
        assert "reachable" in d

    def test_nslookup_host_returns_resolved(self, mcp_client):
        """Should nslookup google.com and return resolved boolean."""
        result = mcp_client.call_tool("nslookup_host", host="google.com")
        data = _parse(result)
        d = data.get("data", {})
        assert d.get("host") == "google.com"
        assert "resolved" in d

    def test_traceroute_host_returns_output(self, mcp_client):
        """Should traceroute to 8.8.8.8 and return host and output."""
        result = mcp_client.call_tool("traceroute_host", host="8.8.8.8")
        data = _parse(result)
        d = data.get("data", {})
        assert d.get("host") == "8.8.8.8"
        assert "output" in d

    def test_wifi_scan_has_networks(self, mcp_client):
        """Should scan wifi and return networks list."""
        result = mcp_client.call_tool("wifi_scan", radio="wlan0")
        data = _parse(result)
        if data["success"] is True:
            assert "networks_found" in data.get("data", {})
            assert isinstance(data["data"].get("networks"), list)

    def test_response_has_meta_envelope(self, mcp_client):
        """_meta envelope should be present on all responses."""
        result = mcp_client.call_tool("get_router_info")
        data = _parse(result)
        assert "_meta" in data, "Response missing _meta envelope"
        meta = data["_meta"]
        assert "request_id" in meta
        assert "duration_ms" in meta
        assert "tool_version" in meta
        assert meta["tool_version"] == TOOLS_VERSION

    def test_get_dhcp_static_leases_has_leases(self, mcp_client):
        """Should return static DHCP reservations with MAC and IP."""
        result = mcp_client.call_tool("get_dhcp_static_leases")
        data = _parse(result)
        if data["success"] is True:
            d = data.get("data", {})
            assert "static_leases_count" in d
            assert "leases" in d
            assert isinstance(d["leases"], list)
            if d["leases"]:
                lease = d["leases"][0]
                assert "mac" in lease
                assert "ip" in lease

    def test_search_router_logs_finds_entries(self, mcp_client):
        """Should search router logs and return matches."""
        result = mcp_client.call_tool("search_router_logs", search_term="dnsmasq", max_results=5)
        data = _parse(result)
        if data["success"] is True:
            d = data.get("data", {})
            assert d.get("search_term") == "dnsmasq"
            assert "results" in d

    def test_search_dhcp_logs_returns_events(self, mcp_client):
        """Should search DHCP logs and return events list."""
        result = mcp_client.call_tool("search_dhcp_logs", search_term="dhcp")
        data = _parse(result)
        if data["success"] is True:
            d = data.get("data", {})
            assert d.get("search_term") == "dhcp"
            assert "events" in d
            assert isinstance(d["events"], list)

    def test_get_device_dhcp_details_by_mac(self, mcp_client):
        """Should return device details for a given MAC address."""
        result = mcp_client.call_tool("get_device_dhcp_details", mac_address="de:ad:be:ef:00:00")
        data = _parse(result)
        d = data.get("data", {})
        assert "device_identifier" in d
        assert d.get("has_static_reservation") in (True, False)
        assert d.get("is_currently_connected") in (True, False)


# ── Mock tests for write tools are in tests/integration/test_write_tools_mocked.py ──
