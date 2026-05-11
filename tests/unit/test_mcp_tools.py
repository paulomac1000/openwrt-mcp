"""Unit tests for MCP tool wrappers — registration and error handling."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openwrt_mcp.tools.registration import register_openwrt_tools
from openwrt_mcp.tools.response_helpers import (
    _error_dict_extended,
    _error_response,
    _error_response_extended,
    _success_response,
)


class TestResponseHelpers:
    """Tests for _success_response and _error_response."""

    def test_success_response(self):
        result = json.loads(_success_response({"key": "value"}))
        assert result == {"success": True, "data": {"key": "value"}}

    def test_success_response_with_list(self):
        result = json.loads(_success_response([1, 2, 3]))
        assert result == {"success": True, "data": [1, 2, 3]}

    def test_error_response(self):
        result = json.loads(_error_response("something broke"))
        assert result == {"success": False, "error": "something broke"}

    def test_error_response_extended(self):
        result = json.loads(
            _error_response_extended("TIMEOUT", "Device offline", True, suggestion="Check power")
        )
        assert result["success"] is False
        assert result["error"]["code"] == "TIMEOUT"
        assert result["error"]["retryable"] is True
        assert result["error"]["suggestion"] == "Check power"

    def test_error_dict_extended_no_suggestion(self):
        result = _error_dict_extended("AUTH_FAILED", "Access denied", False)
        assert result["success"] is False
        assert result["error"]["code"] == "AUTH_FAILED"
        assert "suggestion" not in result["error"]

    def test_error_response_extended_with_available_names(self):
        result = json.loads(
            _error_response_extended(
                "INVALID_PARAM",
                "Unknown device",
                False,
                suggestion="Pick one",
                available_names=["Kitchen", "LivingRoom"],
            )
        )
        assert result["success"] is False
        assert result["error"]["available_names"] == ["Kitchen", "LivingRoom"]


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


class TestToolRegistration:
    """[RULE: TEST-REG-2] Unit tests for MCP tool registration."""

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
    ]

    def test_all_tools_registered(self, mock_mcp):
        """All 13 tools should be registered after calling register_openwrt_tools."""
        register_openwrt_tools(mock_mcp)
        for tool_name in self.EXPECTED_TOOLS:
            assert tool_name in mock_mcp._tools, f"Missing tool: {tool_name}"
        assert len(mock_mcp._tools) == 13

    def test_all_tools_have_read_prefix(self, mock_mcp):
        """Every tool docstring MUST start with [READ]."""
        register_openwrt_tools(mock_mcp)
        for tool_name in self.EXPECTED_TOOLS:
            tool_fn = mock_mcp.get_tool(tool_name)
            doc = (tool_fn.__doc__ or "").strip()
            assert doc.startswith("[READ]"), (
                f"Tool '{tool_name}' docstring missing [READ] prefix: {doc[:50]}"
            )

    @pytest.mark.asyncio
    async def test_tool_accepts_and_returns_json(self, mock_mcp):
        """A tool wrapper should accept params and return valid JSON with success field."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool("get_router_logs")

        with patch("openwrt_mcp.tools.registration.get_explorer") as mock_get:
            mock_explorer = MagicMock()
            mock_ssh = MagicMock()
            mock_explorer.ssh = mock_ssh
            mock_explorer.get_router_logs = AsyncMock(
                return_value={"success": True, "lines_count": 5, "logs": "test"}
            )
            mock_get.return_value = mock_explorer

            result = await tool_fn(lines=10, filter_level="error")
            data = json.loads(result)
            assert data["success"] is True
            assert "data" in data

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name, internal_method, args",
        [
            ("test_router_connection", "test_connection", ()),
            ("get_router_info", "get_system_info", ()),
            ("get_router_wifi_status", "get_wifi_status", ()),
            ("get_router_dhcp_leases", "list_dhcp_leases", ()),
            ("get_router_firewall_rules", "get_firewall_rules", ()),
            ("read_router_uci_config", "read_uci_config", ("dhcp",)),
            ("list_router_packages", "list_installed_packages", ()),
            ("get_router_logs", "get_router_logs", (10, "all")),
            ("search_router_logs", "search_router_logs", ("test", 10)),
            ("diagnose_router_connectivity", "diagnose_router_connectivity", ()),
            ("get_dhcp_static_leases", "get_dhcp_static_leases", ()),
            ("search_dhcp_logs", "search_dhcp_logs", ("dhcp",)),
        ],
    )
    async def test_tool_timeout_seconds_calls_set_timeout(
        self, mock_mcp, tool_name, internal_method, args
    ):
        """Every I/O tool with timeout_seconds should call ssh.set_timeout."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool(tool_name)

        with patch("openwrt_mcp.tools.registration.get_explorer") as mock_get:
            mock_explorer = MagicMock()
            mock_ssh = MagicMock()
            mock_explorer.ssh = mock_ssh
            async_internal = AsyncMock(return_value={"success": True})
            setattr(mock_explorer, internal_method, async_internal)
            mock_get.return_value = mock_explorer

            result = await tool_fn(*args, timeout_seconds=10)
            data = json.loads(result)
            assert data["success"] is True
            mock_ssh.set_timeout.assert_called_once_with(10)


class TestToolErrorHandling:
    """[RULE: TEST-REG-3] Unit tests for exception handlers in tool wrappers."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name",
        [
            "test_router_connection",
            "get_router_info",
            "get_router_wifi_status",
            "get_router_dhcp_leases",
            "get_router_firewall_rules",
            "list_router_packages",
            "diagnose_router_connectivity",
            "get_dhcp_static_leases",
        ],
    )
    async def test_tool_exception_handler_no_args(self, mock_mcp, tool_name):
        """[RULE: TEST-REG-3] Tools with no required args should catch exceptions."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool(tool_name)

        with patch("openwrt_mcp.tools.registration.get_explorer", side_effect=RuntimeError("BOOM")):
            result = await tool_fn()
            data = json.loads(result)
            assert data["success"] is False, f"{tool_name} should fail gracefully"
            assert "BOOM" in data["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name,args",
        [
            ("read_router_uci_config", ("dhcp",)),
            ("get_router_logs", (10, "error")),
            ("search_router_logs", ("test", 10)),
            ("search_dhcp_logs", ("dhcp",)),
            ("get_device_dhcp_details", ("aa:bb:cc:dd:ee:ff", None)),
        ],
    )
    async def test_tool_exception_handler_with_args(self, mock_mcp, tool_name, args):
        """[RULE: TEST-REG-3] Tools WITH params should catch exceptions."""
        register_openwrt_tools(mock_mcp)
        tool_fn = mock_mcp.get_tool(tool_name)

        with patch("openwrt_mcp.tools.registration.get_explorer", side_effect=RuntimeError("BOOM")):
            result = await tool_fn(*args)
            data = json.loads(result)
            assert data["success"] is False, f"{tool_name} should fail gracefully"
            assert "BOOM" in data["error"]
