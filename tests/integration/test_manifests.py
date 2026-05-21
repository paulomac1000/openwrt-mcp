"""Integration tests: verify all tools have manifests with correct risk prefix.

Uses MCPWrapper (Canonical Template 8) instead of direct framework access.
"""

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
def mcp_instance():
    """Create an in-process MCP instance wrapped in MCPWrapper (Template 8)."""
    mcp = FastMCP("OpenWRT-Test")
    register_openwrt_tools(mcp)
    return MCPWrapper(mcp)


EXPECTED_TOOLS = [
    "test_router_connection",
    "get_router_info",
    "get_router_wifi_status",
    "get_router_dhcp_leases",
    "get_router_firewall_rules",
    "read_router_uci_config",
    "list_router_packages",
    "get_router_logs",
    "search_router_logs",
    "diagnose_router_connectivity",
    "get_dhcp_static_leases",
    "search_dhcp_logs",
    "get_device_dhcp_details",
    "get_router_context",
    "describe_router_capabilities",
    "restart_interface",
    "reload_network",
    "uci_set",
    "uci_commit",
    "reboot_device",
    "ping_host",
    "traceroute_host",
    "nslookup_host",
    "wifi_scan",
]

ALL_MANIFEST_KEYS = frozenset(
    {
        "name",
        "version",
        "risk",
        "side_effects",
        "idempotent",
        "retryable",
        "concurrent_safe",
        "timeout_ms",
        "requires_confirmation",
        "determinism",
        "latency",
        "cost",
        "impact",
        "privacy",
        "reversible",
    }
)


class TestIntegrationManifests:
    """Verify all tools have registered via MCPWrapper."""

    def test_all_tools_registered(self, mcp_instance):
        """All 24 tools should be registered."""
        tools = mcp_instance._tools
        assert len(tools) == 24, f"Expected 24 tools, got {len(tools)}"

    def test_all_tools_have_manifest(self, mcp_instance):
        """Every tool should have __manifest__ attribute."""
        for name in EXPECTED_TOOLS:
            tool = mcp_instance.get_tool(name)
            assert tool is not None, f"Missing tool: {name}"
            manifest = getattr(tool, "__manifest__", None)
            assert manifest is not None, f"Tool '{name}' has no __manifest__"
            assert manifest["name"] == name, (
                f"Manifest name mismatch: {manifest.get('name')} != {name}"
            )
            WRITE_TOOLS = frozenset(
                {
                    "restart_interface",
                    "reload_network",
                    "uci_set",
                    "uci_commit",
                }
            )
            DESTRUCTIVE_TOOLS = frozenset({"reboot_device"})
            if name in DESTRUCTIVE_TOOLS:
                expected_risk = "DESTRUCTIVE"
            elif name in WRITE_TOOLS:
                expected_risk = "WRITE"
            else:
                expected_risk = "READ"
            assert manifest["risk"] == expected_risk, (
                f"Tool '{name}' manifest risk mismatch: {manifest['risk']} != {expected_risk}"
            )

    def test_all_manifests_have_all_keys(self, mcp_instance):
        """Every tool manifest should have all required keys."""
        for name in EXPECTED_TOOLS:
            tool = mcp_instance.get_tool(name)
            manifest = getattr(tool, "__manifest__", {})
            missing = ALL_MANIFEST_KEYS - set(manifest.keys())
            assert not missing, f"Tool '{name}' manifest missing keys: {missing}"

    def test_manifest_version_consistency(self, mcp_instance):
        """All manifests should share the same version."""
        versions = set()
        for name in EXPECTED_TOOLS:
            tool = mcp_instance.get_tool(name)
            manifest = getattr(tool, "__manifest__", {})
            versions.add(manifest.get("version"))
        assert len(versions) == 1, f"Inconsistent manifest versions: {versions}"

    def test_read_router_uci_config_validation_error(self, mcp_instance):
        """read_router_uci_config should return error for invalid config."""
        result = mcp_instance.call_tool("read_router_uci_config", config_name="invalid_config_xyz")
        data = json.loads(result)
        assert data["success"] is False
        err = data.get("error", {})
        if isinstance(err, dict):
            assert "code" in err
            assert err["code"] == "INVALID_PARAM"
