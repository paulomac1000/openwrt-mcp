"""Unit tests for UbusClient — internal transport module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openwrt_mcp.tools.ubus_client import UbusClient


class TestUbusClient:
    """Tests for UbusClient internal transport."""

    def test_ubus_client_initialization(self):
        """UbusClient should accept an SSH connection."""
        mock_ssh = MagicMock()
        client = UbusClient(mock_ssh)
        assert client.ssh is mock_ssh

    @pytest.mark.asyncio
    async def test_list_ubus_objects(self):
        """list_ubus_objects should parse ubus list output."""
        client = UbusClient(MagicMock())
        client.ssh.execute = AsyncMock(return_value=("network\nsystem\nwireless\n", "", 0))
        result = await client.list_ubus_objects()
        assert result["success"] is True
        assert result["count"] == 3
        assert "network" in result["objects"]

    @pytest.mark.asyncio
    async def test_list_ubus_objects_fails(self):
        """list_ubus_objects should return error on failure."""
        client = UbusClient(MagicMock())
        client.ssh.execute = AsyncMock(return_value=("", "permission denied", 1))
        result = await client.list_ubus_objects()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_get_system_board(self):
        """get_system_board should call ubus call system board."""
        client = UbusClient(MagicMock())
        client.ssh.execute = AsyncMock(
            return_value=('{"model":{"name":"TestRouter"},"hostname":"test"}', "", 0)
        )
        result = await client.get_system_board()
        assert result["success"] is True
        assert "data" in result

    @pytest.mark.asyncio
    async def test_get_network_devices(self):
        """get_network_devices should call ubus call network.device status."""
        client = UbusClient(MagicMock())
        client.ssh.execute = AsyncMock(return_value=('[0,{"wan":{"up":true}}]', "", 0))
        result = await client.get_network_devices()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_ubus_error_code(self):
        """UbusClient should handle ubus error codes."""
        client = UbusClient(MagicMock())
        client.ssh.execute = AsyncMock(return_value=('[6,{"message":"Permission denied"}]', "", 0))
        result = await client.get_system_board()
        assert result["success"] is False
        assert "error" in result
