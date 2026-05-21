"""Smoke test: every tool returns a valid response contract.

[L3+] Canonical Template 12 — every tool MUST return {"success": bool, ...}.
This test registers all tools on a mock MCP and calls each one with valid
arguments, then verifies the structural contract of the response.
"""

import json

import pytest

from openwrt_mcp.tools.registration import register_openwrt_tools


@pytest.fixture
def mcp_with_tools(mock_mcp):
    """Register all tools on a mock MCP and return it.

    Reuses the project-level ``mock_mcp`` fixture from ``conftest.py``
    (Canonical Template 9) and enriches it with registered tools.
    """
    register_openwrt_tools(mock_mcp)
    return mock_mcp


_REQUIRES_PARAMS = frozenset(
    {
        "read_router_uci_config",
        "search_router_logs",
        "search_dhcp_logs",
        "restart_interface",
        "uci_set",
        "uci_commit",
        "ping_host",
        "traceroute_host",
        "nslookup_host",
    }
)

_VALID_KWARGS = {
    "read_router_uci_config": {"config_name": "network"},
    "search_router_logs": {"search_term": "error"},
    "search_dhcp_logs": {"search_term": "00:11:22:33:44:55"},
    "restart_interface": {"interface_name": "wan"},
    "uci_set": {
        "config": "network",
        "section": "wan",
        "option": "dns",
        "value": "8.8.8.8",
    },
    "uci_commit": {"config": "network"},
    "ping_host": {"host": "127.0.0.1"},
    "traceroute_host": {"host": "127.0.0.1"},
    "nslookup_host": {"host": "localhost"},
}


async def _call_tool(tool_fn, requires_kwargs: bool, tool_name: str):
    if requires_kwargs:
        kwargs = _VALID_KWARGS.get(tool_name, {})
        return await tool_fn(**kwargs)
    return await tool_fn()


def _verify_contract(response_str: str, tool_name: str):
    assert isinstance(response_str, str), (
        f"Tool '{tool_name}' did NOT return a string; got {type(response_str)}"
    )
    data = json.loads(response_str)
    assert "success" in data, f"Tool '{tool_name}' response missing 'success' key"
    assert isinstance(data["success"], bool), (
        f"Tool '{tool_name}' 'success' must be bool, got {type(data['success'])}"
    )
    if data["success"]:
        assert "data" in data, f"Tool '{tool_name}' success response missing 'data' key"
    else:
        assert "error" in data, f"Tool '{tool_name}' failure response missing 'error' key"


class TestResponseContract:
    """Every registered tool MUST return a valid {"success": ..., "data"/"error": ...}."""

    @pytest.mark.asyncio
    async def test_all_tools_return_valid_contract(self, mcp_with_tools, mock_openwrt_ssh):
        for tool_name, tool_fn in sorted(mcp_with_tools._tools.items()):
            needs_params = tool_name in _REQUIRES_PARAMS
            try:
                resp = await _call_tool(tool_fn, needs_params, tool_name)
                _verify_contract(resp, tool_name)
            except Exception as e:
                pytest.fail(
                    f"Tool '{tool_name}' raised {type(e).__name__} instead of returning JSON: {e}"
                )

    @pytest.mark.asyncio
    async def test_destructive_tool_manifest_enforced(self, mcp_with_tools):
        manifest = None
        if hasattr(mcp_with_tools, "_tools") and "reboot_device" in mcp_with_tools._tools:
            fn = mcp_with_tools._tools["reboot_device"]
            manifest = getattr(fn, "__manifest__", None)
        assert manifest is not None, "reboot_device missing __manifest__"
        assert manifest["risk"] == "DESTRUCTIVE"
        assert manifest["requires_confirmation"] is True
        assert manifest["idempotent"] is False
        assert manifest["retryable"] is False
        assert manifest["reversible"] is False
