"""Unit tests for write tool wrappers with mocked SSH — no real router needed.

SAFETY: These tests NEVER execute write commands on a real router.
All internal writer functions are patched with controlled mock responses.
Running dangerous tools (restart_interface, reload_network, reboot_device)
against a production router can cause permanent connectivity loss.

Response fixtures for uci_set and uci_commit come from a real OpenWRT
router (collected using idempotent values — no config changes made).
Remaining tool responses are derived from code structure rather than
real execution, to avoid any risk of router instability.

SAFETY: These tests NEVER execute ifdown/ifup/uci/reboot on a real router.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from openwrt_mcp.tools.registration import register_openwrt_tools
from tests.integration.mcp_wrapper import MCPWrapper

# ── Response fixtures ────────────────────────────────────────────────────
# uci_set and uci_commit responses were collected from a real OpenWRT router
# on 2026-05-12 by executing the idempotent hostname roundtrip.

REAL_UCI_SET_RESPONSE = {
    "success": True,
    "config": "system",
    "section": "@system[0]",
    "option": "hostname",
    "value": "main",
    "action": "uci_set",
}

REAL_UCI_COMMIT_RESPONSE = {
    "success": True,
    "config": "system",
    "action": "uci_committed",
}

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def mcp_client():
    """Create in-process MCP instance with all 24 tools registered."""
    mcp = FastMCP("OpenWRT-Mocked-Write-Test")
    register_openwrt_tools(mcp)
    return MCPWrapper(mcp)


def _parse(response: str) -> dict:
    data = json.loads(response)
    assert "success" in data, f"Response missing 'success': {response[:200]}"
    return data


def _mock_writer(method_name: str, return_value: dict):
    """Create a mock writer with the given async method stubbed."""
    writer = MagicMock()
    method = AsyncMock(return_value=return_value)
    setattr(writer, method_name, method)
    return writer


# ── Tests ────────────────────────────────────────────────────────────────


class TestWriteToolsMocked:
    """Mocked integration tests for dangerous write tools.

    Each test patches get_writer() to return a mock with controlled responses.
    The ENABLE_WRITE_OPERATIONS flag is also patched to allow execution.

    Tests never make real SSH calls — the writer layer is fully mocked.
    """

    def _call_with_mock(self, mcp_client, tool_name: str, writer_data: dict, **kwargs):
        """Call a write tool with the writer mocked."""
        mock_writer = _mock_writer(tool_name, writer_data)
        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer"),
            patch("openwrt_mcp.tools.registration.get_writer", return_value=mock_writer),
        ):
            result = mcp_client.call_tool(tool_name, **kwargs)
            return json.loads(result)

    def _assert_blocks(self, mcp_client, tool_name: str, **kwargs):
        """Assert a write tool returns error when write ops disabled."""
        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", False):
            result = mcp_client.call_tool(tool_name, **kwargs)
            data = json.loads(result)
            assert data["success"] is False

    # ── restart_interface ──────────────────────────────────────────────

    def test_restart_interface_mocked_success(self, mcp_client):
        data = self._call_with_mock(
            mcp_client,
            "restart_interface",
            {"success": True, "interface": "lan", "action": "restarted"},
            interface_name="lan",
        )
        assert data["success"] is True
        assert data["data"]["action"] == "restarted"
        assert data["data"]["interface"] == "lan"

    def test_restart_interface_blocks_without_flag(self, mcp_client):
        self._assert_blocks(mcp_client, "restart_interface", interface_name="lan")

    # ── reload_network ────────────────────────────────────────────────

    def test_reload_network_mocked_success(self, mcp_client):
        data = self._call_with_mock(
            mcp_client,
            "reload_network",
            {"success": True, "action": "network_reloaded"},
        )
        assert data["success"] is True
        assert data["data"]["action"] == "network_reloaded"

    def test_reload_network_blocks_without_flag(self, mcp_client):
        self._assert_blocks(mcp_client, "reload_network")

    # ── reboot_device ─────────────────────────────────────────────────

    def test_reboot_device_mocked_success(self, mcp_client):
        data = self._call_with_mock(
            mcp_client,
            "reboot_device",
            {"success": True, "action": "reboot_initiated"},
        )
        assert data["success"] is True
        assert data["data"]["action"] == "reboot_initiated"

    def test_reboot_device_blocks_without_flag(self, mcp_client):
        self._assert_blocks(mcp_client, "reboot_device")

    # ── uci_set (response from real router) ─────────────────────────────

    def test_uci_set_mocked_success(self, mcp_client):
        data = self._call_with_mock(
            mcp_client,
            "uci_set",
            REAL_UCI_SET_RESPONSE,
            config="system",
            section="@system[0]",
            option="hostname",
            value="main",
        )
        assert data["success"] is True
        assert data["data"]["config"] == "system"
        assert data["data"]["option"] == "hostname"
        assert data["data"]["value"] == "main"
        assert data["data"]["action"] == "uci_set"

    def test_uci_set_blocks_without_flag(self, mcp_client):
        self._assert_blocks(
            mcp_client,
            "uci_set",
            config="system",
            section="@system[0]",
            option="hostname",
            value="main",
        )

    # ── uci_commit (response from real router) ─────────────────────────

    def test_uci_commit_mocked_success(self, mcp_client):
        data = self._call_with_mock(
            mcp_client,
            "uci_commit",
            REAL_UCI_COMMIT_RESPONSE,
            config="system",
        )
        assert data["success"] is True
        assert data["data"]["config"] == "system"
        assert data["data"]["action"] == "uci_committed"

    def test_uci_commit_blocks_without_flag(self, mcp_client):
        self._assert_blocks(mcp_client, "uci_commit", config="system")
