"""Unit tests for write tool wrappers — registration, validation, and error handling."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openwrt_mcp.tools.registration import register_openwrt_tools
from openwrt_mcp.tools.writer import OpenWRTWriter, check_write_enabled, get_writer
from openwrt_mcp.validators import ValidationError


@pytest.fixture
def mock_mcp():
    """Mock MCP instance that stores registered tools — Canonical Template 9."""
    mcp = MagicMock()
    mcp._tools = {}

    def tool_decorator(*args, **kwargs):
        def wrapper(func):
            tool_name = kwargs.get("name", func.__name__)
            mcp._tools[tool_name] = func
            return func

        if len(args) == 1 and callable(args[0]) and not kwargs:
            mcp._tools[args[0].__name__] = args[0]
            return args[0]
        return wrapper

    mcp.tool = tool_decorator
    mcp.get_tool = lambda name: mcp._tools.get(name)
    return mcp


class TestWriteToolsRegistration:
    """[RULE: TEST-REG-2] Unit tests for write tool registration."""

    WRITE_TOOLS = [
        "restart_interface",
        "reload_network",
        "uci_set",
        "uci_commit",
        "reboot_device",
    ]

    def test_write_tools_are_registered(self, mock_mcp):
        """Write tools should be registered along with all other tools."""
        register_openwrt_tools(mock_mcp)
        for tool_name in self.WRITE_TOOLS:
            assert tool_name in mock_mcp._tools, f"Missing tool: {tool_name}"

    def test_write_tools_have_correct_manifest(self, mock_mcp):
        """Write tools must have risk: WRITE and requires_confirmation: true."""
        register_openwrt_tools(mock_mcp)
        for tool_name in self.WRITE_TOOLS:
            tool_fn = mock_mcp.get_tool(tool_name)
            manifest = getattr(tool_fn, "__manifest__", None)
            assert manifest is not None, f"Tool '{tool_name}' missing __manifest__"
            assert manifest["risk"] == "WRITE", f"Tool '{tool_name}' risk should be WRITE"
            assert manifest["requires_confirmation"] is True, (
                f"Tool '{tool_name}' should require confirmation"
            )
            assert manifest["impact"] in ("transient", "persistent", "service_outage"), (
                f"Tool '{tool_name}' impact should be one of transient/persistent/service_outage"
            )


class TestRestartInterface:
    """Unit tests for restart_interface write tool."""

    @pytest.mark.asyncio
    async def test_restart_interface_blocks_when_write_disabled(self, mock_mcp):
        """[RULE: TEST-REG-3] restart_interface returns error when write ops disabled."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("restart_interface")

        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", False):
            result = await tool_fn(interface_name="wan")
            data = json.loads(result)
            assert data["success"] is False
            assert "INVALID_PARAM" in json.dumps(data["error"])

    @pytest.mark.asyncio
    async def test_restart_interface_requires_valid_name(self, mock_mcp):
        """restart_interface should validate interface name format."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("restart_interface")

        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True):
            result = await tool_fn(interface_name="../../etc/passwd")
            data = json.loads(result)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_restart_interface_blocks_loopback(self, mock_mcp):
        """Loopback interface 'lo' should be blocked from restart."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("restart_interface")

        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True):
            result = await tool_fn(interface_name="lo")
            data = json.loads(result)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_restart_interface_calls_ifdown_ifup(self, mock_mcp):
        """restart_interface should call ifdown and ifup when enabled."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("restart_interface")

        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer") as mock_get,
            patch("openwrt_mcp.tools.registration.get_writer") as mock_writer_get,
        ):
            mock_explorer = MagicMock()
            mock_ssh = MagicMock()
            mock_explorer.ssh = mock_ssh
            mock_get.return_value = mock_explorer

            mock_writer = MagicMock()
            mock_writer.restart_interface = AsyncMock(
                return_value={
                    "success": True,
                    "interface": "wan",
                    "action": "restarted",
                }
            )
            mock_writer_get.return_value = mock_writer

            result = await tool_fn(interface_name="wan")
            data = json.loads(result)
            assert data["success"] is True
            assert data["data"]["interface"] == "wan"

    @pytest.mark.asyncio
    async def test_restart_interface_exception_handler(self, mock_mcp):
        """[RULE: TEST-REG-3] restart_interface should catch exceptions."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("restart_interface")

        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer", side_effect=RuntimeError("BOOM")),
        ):
            result = await tool_fn(interface_name="wan")
            data = json.loads(result)
            assert data["success"] is False
            assert "BOOM" in data["error"]


class TestReloadNetwork:
    """Unit tests for reload_network write tool."""

    @pytest.mark.asyncio
    async def test_reload_network_blocks_when_write_disabled(self, mock_mcp):
        """[RULE: TEST-REG-3] reload_network returns error when ENABLE_WRITE_OPERATIONS is false."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("reload_network")

        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", False):
            result = await tool_fn()
            data = json.loads(result)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_reload_network_exception_handler(self, mock_mcp):
        """[RULE: TEST-REG-3] reload_network should catch exceptions."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("reload_network")

        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer", side_effect=RuntimeError("BOOM")),
        ):
            result = await tool_fn()
            data = json.loads(result)
            assert data["success"] is False
            assert "BOOM" in data["error"]


class TestUciSet:
    """Unit tests for uci_set write tool."""

    @pytest.mark.asyncio
    async def test_uci_set_blocks_when_write_disabled(self, mock_mcp):
        """[RULE: TEST-REG-3] uci_set returns error when write ops disabled."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("uci_set")

        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", False):
            result = await tool_fn(
                config="network", section="wan", option="ipaddr", value="10.0.0.1"
            )
            data = json.loads(result)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_uci_set_calls_writer(self, mock_mcp):
        """uci_set should call writer.uci_set when enabled."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("uci_set")

        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer") as mock_get,
            patch("openwrt_mcp.tools.registration.get_writer") as mock_writer_get,
        ):
            mock_explorer = MagicMock()
            mock_explorer.ssh = MagicMock()
            mock_get.return_value = mock_explorer

            mock_writer = MagicMock()
            mock_writer.uci_set = AsyncMock(
                return_value={"success": True, "config": "network", "action": "uci_set"}
            )
            mock_writer_get.return_value = mock_writer

            result = await tool_fn(
                config="network", section="wan", option="ipaddr", value="10.0.0.1"
            )
            data = json.loads(result)
            assert data["success"] is True
            assert data["data"]["config"] == "network"

    @pytest.mark.asyncio
    async def test_uci_set_exception_handler(self, mock_mcp):
        """[RULE: TEST-REG-3] uci_set should catch exceptions."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("uci_set")

        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer", side_effect=RuntimeError("BOOM")),
        ):
            result = await tool_fn(
                config="network", section="wan", option="ipaddr", value="10.0.0.1"
            )
            data = json.loads(result)
            assert data["success"] is False
            assert "BOOM" in data["error"]


class TestUciCommit:
    """Unit tests for uci_commit write tool."""

    @pytest.mark.asyncio
    async def test_uci_commit_blocks_when_write_disabled(self, mock_mcp):
        """[RULE: TEST-REG-3] uci_commit returns error when write ops disabled."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("uci_commit")

        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", False):
            result = await tool_fn(config="network")
            data = json.loads(result)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_uci_commit_exception_handler(self, mock_mcp):
        """[RULE: TEST-REG-3] uci_commit should catch exceptions."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("uci_commit")

        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer", side_effect=RuntimeError("BOOM")),
        ):
            result = await tool_fn(config="network")
            data = json.loads(result)
            assert data["success"] is False
            assert "BOOM" in data["error"]


class TestRebootDevice:
    """Unit tests for reboot_device write tool."""

    @pytest.mark.asyncio
    async def test_reboot_blocks_when_write_disabled(self, mock_mcp):
        """[RULE: TEST-REG-3] reboot_device returns error when write ops disabled."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("reboot_device")

        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", False):
            result = await tool_fn()
            data = json.loads(result)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_reboot_calls_writer(self, mock_mcp):
        """reboot_device should call writer.reboot_device when enabled."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("reboot_device")

        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer") as mock_get,
            patch("openwrt_mcp.tools.registration.get_writer") as mock_writer_get,
        ):
            mock_explorer = MagicMock()
            mock_explorer.ssh = MagicMock()
            mock_get.return_value = mock_explorer

            mock_writer = MagicMock()
            mock_writer.reboot_device = AsyncMock(
                return_value={"success": True, "action": "reboot_initiated"}
            )
            mock_writer_get.return_value = mock_writer

            result = await tool_fn()
            data = json.loads(result)
            assert data["success"] is True
            assert data["data"]["action"] == "reboot_initiated"

    @pytest.mark.asyncio
    async def test_reboot_exception_handler(self, mock_mcp):
        """[RULE: TEST-REG-3] reboot_device should catch exceptions."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("reboot_device")

        with (
            patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True),
            patch("openwrt_mcp.tools.registration.get_explorer", side_effect=RuntimeError("BOOM")),
        ):
            result = await tool_fn()
            data = json.loads(result)
            assert data["success"] is False
            assert "BOOM" in data["error"]


class TestOpenWRTWriterInternal:
    """Unit tests for OpenWRTWriter internal functions."""

    async def _setup_writer(self, enabled: bool = True):
        """Helper to create a writer with mocked SSH."""
        writer = OpenWRTWriter(MagicMock())
        writer.ssh.execute_write = AsyncMock(return_value=("", "", 0))
        return writer

    @pytest.mark.asyncio
    async def test_restart_interface_success(self):
        """restart_interface should return success when ifdown/ifup succeed."""
        writer = await self._setup_writer()
        result = await writer.restart_interface("wan")
        assert result["success"] is True
        assert result["interface"] == "wan"
        assert result["action"] == "restarted"

    @pytest.mark.asyncio
    async def test_restart_interface_ifdown_fails(self):
        """restart_interface should return error when ifdown fails."""
        writer = OpenWRTWriter(MagicMock())
        writer.ssh.execute_write = AsyncMock(
            side_effect=[
                ("", "error bringing down", 1),
            ]
        )
        result = await writer.restart_interface("wan")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_reload_network_success(self):
        """reload_network should return success."""
        writer = await self._setup_writer()
        result = await writer.reload_network()
        assert result["success"] is True
        assert result["action"] == "network_reloaded"

    @pytest.mark.asyncio
    async def test_reload_network_fails(self):
        """reload_network should return error when network reload fails."""
        writer = OpenWRTWriter(MagicMock())
        writer.ssh.execute_write = AsyncMock(return_value=("", "error", 1))
        result = await writer.reload_network()
        assert result["success"] is False

    def test_check_write_enabled_raises_when_disabled(self):
        """check_write_enabled should raise when write operations are disabled."""
        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", False):
            with pytest.raises(ValidationError):
                check_write_enabled()

    def test_check_write_enabled_passes_when_enabled(self):
        """check_write_enabled should not raise when write operations are enabled."""
        with patch("openwrt_mcp.tools.writer.ENABLE_WRITE_OPERATIONS", True):
            check_write_enabled()

    def test_get_writer_singleton(self):
        """get_writer should return the same instance."""
        ssh = MagicMock()
        w1 = get_writer(ssh)
        w2 = get_writer(ssh)
        assert w1 is w2

    def test_get_writer_is_openwrt_writer(self):
        """get_writer should return an OpenWRTWriter."""
        ssh = MagicMock()
        writer = get_writer(ssh)
        assert isinstance(writer, OpenWRTWriter)

    @pytest.mark.asyncio
    async def test_uci_set_success(self):
        """uci_set should return success."""
        writer = await self._setup_writer()
        result = await writer.uci_set("network", "wan", "ipaddr", "10.0.0.1")
        assert result["success"] is True
        assert result["action"] == "uci_set"
        assert result["config"] == "network"

    @pytest.mark.asyncio
    async def test_uci_set_fails(self):
        """uci_set should return error when SSH fails."""
        writer = OpenWRTWriter(MagicMock())
        writer.ssh.execute_write = AsyncMock(return_value=("", "uci error", 1))
        result = await writer.uci_set("network", "wan", "ipaddr", "10.0.0.1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_uci_commit_success(self):
        """uci_commit should return success."""
        writer = await self._setup_writer()
        result = await writer.uci_commit("network")
        assert result["success"] is True
        assert result["action"] == "uci_committed"

    @pytest.mark.asyncio
    async def test_uci_commit_fails(self):
        """uci_commit should return error when SSH fails."""
        writer = OpenWRTWriter(MagicMock())
        writer.ssh.execute_write = AsyncMock(return_value=("", "commit error", 1))
        result = await writer.uci_commit("network")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_reboot_device_success(self):
        """reboot_device should return success."""
        writer = await self._setup_writer()
        result = await writer.reboot_device()
        assert result["success"] is True
        assert result["action"] == "reboot_initiated"

    @pytest.mark.asyncio
    async def test_reboot_device_fails(self):
        """reboot_device should return error when SSH fails."""
        writer = OpenWRTWriter(MagicMock())
        writer.ssh.execute_write = AsyncMock(return_value=("", "denied", 1))
        result = await writer.reboot_device()
        assert result["success"] is False
