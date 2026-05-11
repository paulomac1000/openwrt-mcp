"""MCP tool registration — all 13 OpenWRT tools wrapped as MCP tools."""

import logging
import time
from typing import Any

from openwrt_mcp.observability import build_meta
from openwrt_mcp.tools.explorer import get_explorer
from openwrt_mcp.tools.response_helpers import (
    _error_response,
    _error_response_extended,
    _success_response,
)
from openwrt_mcp.validators import ValidationError

logger = logging.getLogger("openwrt-mcp.tools")
TOOLS_VERSION = "1.1.0"


def _make_manifest(
    name: str,
    timeout_ms: int = 15000,
    latency: str = "moderate",
) -> dict[str, Any]:
    """Create a READ-only tool manifest."""
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "READ",
        "side_effects": "read",
        "idempotent": True,
        "retryable": True,
        "concurrent_safe": False,  # SSHConnection.execute() shares mutable state without locking
        "timeout_ms": timeout_ms,
        "requires_confirmation": False,
        "determinism": "env-dependent",
        "latency": latency,
        "cost": "cheap",
    }


def register_openwrt_tools(mcp: Any) -> None:
    """[READ] Register OpenWRT tools in the MCP server."""

    @mcp.tool()
    async def test_router_connection(timeout_seconds: int | None = None) -> str:
        """[READ] Test SSH connection to the OpenWRT router.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, status (connected/disconnected),
            host, model, and release version.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.test_connection()
            return _success_response(result, _meta=build_meta("test_router_connection", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_info(timeout_seconds: int | None = None) -> str:
        """[READ] Fetch router system info (model, version, memory, uptime).

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, data containing model, hostname,
            openwrt_version, kernel, uptime, and memory stats.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_system_info()
            return _success_response(result, _meta=build_meta("get_router_info", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_wifi_status(timeout_seconds: int | None = None) -> str:
        """[READ] Fetch WiFi status and list of connected clients.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, interfaces_count, interfaces list
            with SSID, mode, radio, and connected clients.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_wifi_status()
            return _success_response(result, _meta=build_meta("get_router_wifi_status", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_dhcp_leases(timeout_seconds: int | None = None) -> str:
        """[READ] Fetch active DHCP leases.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, leases_count, and leases list
            with MAC, IP, hostname, and expiry.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.list_dhcp_leases()
            return _success_response(result, _meta=build_meta("get_router_dhcp_leases", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_firewall_rules(timeout_seconds: int | None = None) -> str:
        """[READ] Fetch firewall rules (iptables/nftables/fw4).

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, firewall_type, rules_preview,
            and full_output_truncated boolean.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_firewall_rules()
            return _success_response(result, _meta=build_meta("get_router_firewall_rules", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def read_router_uci_config(config_name: str, timeout_seconds: int | None = None) -> str:
        """[READ] Read UCI configuration (dhcp, network, wireless, firewall, system).

        Args:
            config_name: UCI configuration name (e.g., dhcp, network, wireless).
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, config_name, entries_count, and sample.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.read_uci_config(config_name)
            return _success_response(result, _meta=build_meta("read_router_uci_config", _start))
        except ValidationError as e:
            return _error_response_extended(
                "INVALID_PARAM",
                str(e),
                False,
                suggestion="Check the configuration name and try again.",
            )
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def list_router_packages(timeout_seconds: int | None = None) -> str:
        """[READ] Fetch list of installed OpenWRT packages.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, packages_count, and packages_sample
            list with name and version.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.list_installed_packages()
            return _success_response(result, _meta=build_meta("list_router_packages", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_logs(
        lines: int = 50, filter_level: str = "all", timeout_seconds: int | None = None
    ) -> str:
        """[READ] Fetch router system logs.

        Args:
            lines: Number of log lines to return (10-200, default 50).
            filter_level: Filter logs by keyword or "all" (default "all").
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, lines_count, and logs text.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_router_logs(lines, filter_level)
            return _success_response(result, _meta=build_meta("get_router_logs", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def search_router_logs(
        search_term: str, max_results: int = 30, timeout_seconds: int | None = None
    ) -> str:
        """[READ] Search for a phrase in router logs.

        Args:
            search_term: Phrase to search for in log entries.
            max_results: Maximum number of matching results (default 30).
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, search_term, results_count, and results text.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.search_router_logs(search_term, max_results)
            if isinstance(result, dict) and result.get("success") is False:
                err = result.get("error", {})
                if isinstance(err, dict):
                    return _error_response_extended(
                        err.get("code", "UNKNOWN"),
                        err.get("message", str(err)),
                        err.get("retryable", False),
                        suggestion=err.get("suggestion"),
                    )
                return _error_response(str(err))
            return _success_response(result, _meta=build_meta("search_router_logs", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def diagnose_router_connectivity(
        timeout_seconds: int | None = None,
    ) -> str:
        """[READ] Test router internet connectivity (ping, DNS).

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, tests dict per service, and
            summary with passed/failed/total counts and health rating.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.diagnose_router_connectivity()

            return _success_response(
                result, _meta=build_meta("diagnose_router_connectivity", _start)
            )
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_dhcp_static_leases(timeout_seconds: int | None = None) -> str:
        """[READ] Fetch static DHCP reservations.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, static_leases_count, and leases list
            with MAC, IP, and hostname.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_dhcp_static_leases()
            return _success_response(result, _meta=build_meta("get_dhcp_static_leases", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def search_dhcp_logs(
        search_term: str,
        timeout_seconds: int | None = None,
    ) -> str:
        """[READ] Search DHCP events in router logs.

        Args:
            search_term: MAC address, IP, or hostname to search for.
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, search_term, events_found, and
            events list with raw_log, event_type, and contains_search_term.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.search_dhcp_logs(search_term)
            if isinstance(result, dict) and result.get("success") is False:
                err = result.get("error", {})
                if isinstance(err, dict):
                    return _error_response_extended(
                        err.get("code", "UNKNOWN"),
                        err.get("message", str(err)),
                        err.get("retryable", False),
                        suggestion=err.get("suggestion"),
                    )
                return _error_response(str(err))
            return _success_response(result, _meta=build_meta("search_dhcp_logs", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_device_dhcp_details(
        mac_address: str | None = None,
        ip_address: str | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        """[READ] Fetch DHCP device details (lease, reservation, logs).

        Args:
            mac_address: MAC address to look up (format aa:bb:cc:dd:ee:ff).
            ip_address: IP address to look up (format 192.168.1.100).
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, device_identifier, current_lease,
            static_reservation, has_static_reservation, is_currently_connected,
            and recent_log_events.

        @since v1.0.0
        """
        _start = time.monotonic()
        try:
            explorer = get_explorer()
            if timeout_seconds is not None:
                explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_device_dhcp_details(mac_address, ip_address)
            if isinstance(result, dict) and result.get("success") is False:
                err = result.get("error", {})
                if isinstance(err, dict):
                    return _error_response_extended(
                        err.get("code", "UNKNOWN"),
                        err.get("message", str(err)),
                        err.get("retryable", False),
                        suggestion=err.get("suggestion"),
                    )
                return _error_response(str(err))
            return _success_response(result, _meta=build_meta("get_device_dhcp_details", _start))
        except ValidationError as e:
            return _error_response_extended(
                "INVALID_PARAM",
                str(e),
                False,
                suggestion="Provide a valid MAC (aa:bb:cc:dd:ee:ff) or IP address.",
            )
        except Exception as e:
            return _error_response(str(e))

    # Attach manifests to all tools
    tool_manifest_map = {
        "test_router_connection": _make_manifest("test_router_connection", 10000, "moderate"),
        "get_router_info": _make_manifest("get_router_info"),
        "get_router_wifi_status": _make_manifest("get_router_wifi_status"),
        "get_router_dhcp_leases": _make_manifest("get_router_dhcp_leases"),
        "get_router_firewall_rules": _make_manifest("get_router_firewall_rules"),
        "read_router_uci_config": _make_manifest("read_router_uci_config"),
        "list_router_packages": _make_manifest("list_router_packages"),
        "get_router_logs": _make_manifest("get_router_logs"),
        "search_router_logs": _make_manifest("search_router_logs", 30000, "slow"),
        "diagnose_router_connectivity": _make_manifest(
            "diagnose_router_connectivity", 30000, "slow"
        ),
        "get_dhcp_static_leases": _make_manifest("get_dhcp_static_leases"),
        "search_dhcp_logs": _make_manifest("search_dhcp_logs", 30000, "slow"),
        "get_device_dhcp_details": _make_manifest("get_device_dhcp_details"),
    }
    try:
        tm = getattr(mcp, "_tool_manager", None)
        all_tools = getattr(mcp, "_tools", {}) or (getattr(tm, "_tools", {}) if tm else {})
        for name, fn in all_tools.items():
            if name in tool_manifest_map:
                fn.__manifest__ = tool_manifest_map[name]
    except Exception:
        pass

    tool_count = len(all_tools) if "all_tools" in dir() else 0
    if tool_count == 0:
        try:
            tm2 = getattr(mcp, "_tool_manager", None)
            tool_count = len(
                getattr(mcp, "_tools", {}) or (getattr(tm2, "_tools", {}) if tm2 else {})
            )
        except Exception:
            pass
    logger.info("Registered %d tools", tool_count)
