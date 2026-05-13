"""MCP tool registration — all 24 OpenWRT tools wrapped as MCP tools."""

import asyncio
import logging
import time
from typing import Any

from openwrt_mcp.observability import build_meta, generate_request_id, set_request_id
from openwrt_mcp.tools.constants import SSH_TIMEOUT
from openwrt_mcp.tools.explorer import get_explorer
from openwrt_mcp.tools.response_helpers import (
    _error_response,
    _error_response_extended,
    _success_response,
)
from openwrt_mcp.tools.writer import check_write_enabled, get_writer
from openwrt_mcp.validators import ValidationError

logger = logging.getLogger("openwrt-mcp.tools")
TOOLS_VERSION = "1.2.0"


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
        "impact": "none",
        "privacy": "none",
        "reversible": True,
    }


def _make_write_manifest(
    name: str,
    timeout_ms: int = 15000,
    latency: str = "moderate",
) -> dict[str, Any]:
    """Create a WRITE tool manifest."""
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "WRITE",
        "side_effects": "write",
        "idempotent": True,
        "retryable": True,
        "concurrent_safe": False,
        "timeout_ms": timeout_ms,
        "requires_confirmation": True,
        "determinism": "env-dependent",
        "latency": latency,
        "cost": "moderate",
        "impact": "persistent",
        "privacy": "none",
        "reversible": True,
    }


def _inject_risk_prefixes(all_tools: dict[str, Any], manifest_map: dict[str, Any]) -> None:
    """Inject risk prefixes into tool docstrings from manifest SSOT.

    [L2+] Standards Rule 1.1: Risk annotations in docstrings MUST NOT
    be manually authored if a manifest exists; they are dynamically
    injected from the manifest (Single Source of Truth).
    """
    KNOWN_PREFIXES = frozenset({"[READ]", "[WRITE]", "[DANGEROUS]", "[DESTRUCTIVE]", "[SENSITIVE]"})
    for name, fn in all_tools.items():
        manifest = manifest_map.get(name, {})
        risk = manifest.get("risk", "READ")
        # Tool objects wrap the raw function — unwrap to reach __doc__
        raw_fn = fn
        for attr in ("fn", "func", "_func", "function"):
            if hasattr(fn, attr):
                inner = getattr(fn, attr)
                if callable(inner):
                    raw_fn = inner
                    break
        doc = (raw_fn.__doc__ or "").strip()
        for prefix in KNOWN_PREFIXES:
            if doc.startswith(prefix):
                doc = doc[len(prefix) :].lstrip()
                break
        new_doc = f"[{risk}] {doc}"
        raw_fn.__doc__ = new_doc
        # Also update Tool.description if it's a FastMCP Tool object
        if hasattr(fn, "description"):
            try:
                fn.description = new_doc.split("\n")[0].rstrip(".")
            except Exception:
                pass


def register_openwrt_tools(mcp: Any) -> None:
    """Register OpenWRT tools in the MCP server."""

    @mcp.tool()
    async def test_router_connection(timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Test SSH connection to the OpenWRT router.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, status (connected/disconnected),
            host, model, and release version.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.test_connection()
            return _success_response(result, _meta=build_meta("test_router_connection", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_info(timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Fetch router system info (model, version, memory, uptime).

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, data containing model, hostname,
            openwrt_version, kernel, uptime, and memory stats.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_system_info()
            return _success_response(result, _meta=build_meta("get_router_info", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_wifi_status(timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Fetch WiFi status and list of connected clients.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, interfaces_count, interfaces list
            with SSID, mode, radio, and connected clients.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_wifi_status()
            return _success_response(result, _meta=build_meta("get_router_wifi_status", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_dhcp_leases(timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Fetch active DHCP leases.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, leases_count, and leases list
            with MAC, IP, hostname, and expiry.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.list_dhcp_leases()
            return _success_response(result, _meta=build_meta("get_router_dhcp_leases", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_firewall_rules(timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Fetch firewall rules (iptables/nftables/fw4).

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, firewall_type, rules_preview,
            and full_output_truncated boolean.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_firewall_rules()
            return _success_response(result, _meta=build_meta("get_router_firewall_rules", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def read_router_uci_config(config_name: str, timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Read UCI configuration (dhcp, network, wireless, firewall, system).

        Args:
            config_name: UCI configuration name (e.g., dhcp, network, wireless).
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, config_name, entries_count, and sample.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
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
    async def list_router_packages(timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Fetch list of installed OpenWRT packages.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, packages_count, and packages_sample
            list with name and version.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.list_installed_packages()
            return _success_response(result, _meta=build_meta("list_router_packages", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_router_logs(
        lines: int = 50, filter_level: str = "all", timeout_seconds: int = SSH_TIMEOUT
    ) -> str:
        """Fetch router system logs.

        Args:
            lines: Number of log lines to return (10-200, default 50).
            filter_level: Filter logs by keyword or "all" (default "all").
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, lines_count, and logs text.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_router_logs(lines, filter_level)
            return _success_response(result, _meta=build_meta("get_router_logs", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def search_router_logs(
        search_term: str, max_results: int = 30, timeout_seconds: int = SSH_TIMEOUT
    ) -> str:
        """Search for a phrase in router logs.

        Args:
            search_term: Phrase to search for in log entries.
            max_results: Maximum number of matching results (default 30).
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, search_term, results_count, and results text.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
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
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Test router internet connectivity (ping, DNS).

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, tests dict per service, and
            summary with passed/failed/total counts and health rating.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.diagnose_router_connectivity()

            return _success_response(
                result, _meta=build_meta("diagnose_router_connectivity", _start)
            )
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def get_dhcp_static_leases(timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Fetch static DHCP reservations.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, static_leases_count, and leases list
            with MAC, IP, and hostname.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_dhcp_static_leases()
            return _success_response(result, _meta=build_meta("get_dhcp_static_leases", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def search_dhcp_logs(
        search_term: str,
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Search DHCP events in router logs.

        Args:
            search_term: MAC address, IP, or hostname to search for.
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, search_term, events_found, and
            events list with raw_log, event_type, and contains_search_term.

        @since v1.0.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
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
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Fetch DHCP device details (lease, reservation, logs).

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
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
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

    @mcp.tool()
    async def get_router_context(timeout_seconds: int = SSH_TIMEOUT) -> str:
        """Fetch unified router context snapshot (system, wifi, DHCP, connectivity).

        Aggregates system info, WiFi status, DHCP lease count, and connectivity
        health into a single response. Partial failures degrade gracefully
        with per-subsection success flags.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, device_id, model, uptime_seconds,
            subsections dict with per-call success/error, and aggregated fields.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.get_router_context()
            return _success_response(result, _meta=build_meta("get_router_context", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def describe_router_capabilities() -> str:
        """Introspect server capabilities: tools, contexts, transports, version.

        Returns a complete catalog of all registered MCP tools with their
        manifests (risk, timeout, latency), context collectors, and
        supported transports. Zero I/O — always instant.

        Returns:
            JSON string with server, version, schema_version,
            transports, tools list with manifests, total_tools count.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            capabilities = explorer.describe_capabilities()

            # Collect manifests from all registered tools
            all_tools_mcp = getattr(mcp, "_tools", {})
            if not all_tools_mcp:
                tm = getattr(mcp, "_tool_manager", None)
                if tm:
                    all_tools_mcp = getattr(tm, "_tools", {})
            tools_list = []
            for name, fn in sorted(all_tools_mcp.items()):
                manifest = getattr(fn, "__manifest__", None)
                tools_list.append(
                    manifest or {"name": name, "version": TOOLS_VERSION, "risk": "READ"}
                )

            capabilities["version"] = TOOLS_VERSION
            capabilities["tools"] = tools_list
            capabilities["total_tools"] = len(tools_list)
            return _success_response(
                capabilities, _meta=build_meta("describe_router_capabilities", _start)
            )
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def restart_interface(
        interface_name: str,
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Restart a network interface (ifdown + ifup).

        Requires ENABLE_WRITE_OPERATIONS=1 to be set.

        Args:
            interface_name: Network interface name (e.g., "wan", "lan", "wwan0").
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, interface, action, and command output.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            check_write_enabled()
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            writer = get_writer(explorer.ssh)
            result = await writer.restart_interface(interface_name)
            return _success_response(result, _meta=build_meta("restart_interface", _start))
        except ValidationError as e:
            return _error_response_extended(
                "INVALID_PARAM",
                str(e),
                False,
                suggestion="Set ENABLE_WRITE_OPERATIONS=1 to enable write"
                " tools, or use a valid interface name.",
            )
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def reload_network(
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Reload the network service (/etc/init.d/network reload).

        Requires ENABLE_WRITE_OPERATIONS=1 to be set.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, action, and command output.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            check_write_enabled()
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            writer = get_writer(explorer.ssh)
            result = await writer.reload_network()
            return _success_response(result, _meta=build_meta("reload_network", _start))
        except ValidationError as e:
            return _error_response_extended(
                "INVALID_PARAM",
                str(e),
                False,
                suggestion="Set ENABLE_WRITE_OPERATIONS=1 to enable write tools.",
            )
        except Exception as e:
            return _error_response(str(e))

    # ------------------------------------------------------------------ #
    # Feature 1: UCI Write tools
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def uci_set(
        config: str,
        section: str,
        option: str,
        value: str,
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Set a UCI configuration value on the router.

        Requires ENABLE_WRITE_OPERATIONS=1 to be set.
        Changes are not permanent until uci_commit is called.

        Args:
            config: UCI config name (e.g., 'network', 'dhcp', 'wireless').
            section: Section identifier (e.g., 'wan', '@rule[0]').
            option: Option name (e.g., 'ipaddr', 'hostname').
            value: Value to set.
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, config, section, option, value, action.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            check_write_enabled()
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            writer = get_writer(explorer.ssh)
            result = await writer.uci_set(config, section, option, value)
            return _success_response(result, _meta=build_meta("uci_set", _start))
        except ValidationError as e:
            return _error_response_extended(
                "INVALID_PARAM",
                str(e),
                False,
                suggestion="Set ENABLE_WRITE_OPERATIONS=1 to enable write tools,"
                " and use valid config/section/option names.",
            )
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def uci_commit(
        config: str,
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Commit UCI configuration changes to make them permanent.

        Requires ENABLE_WRITE_OPERATIONS=1 to be set.

        Args:
            config: UCI config name to commit (e.g., 'dhcp', 'network', 'wireless').
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, config, action.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            check_write_enabled()
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            writer = get_writer(explorer.ssh)
            result = await writer.uci_commit(config)
            return _success_response(result, _meta=build_meta("uci_commit", _start))
        except ValidationError as e:
            return _error_response_extended(
                "INVALID_PARAM",
                str(e),
                False,
                suggestion="Set ENABLE_WRITE_OPERATIONS=1 to enable write tools.",
            )
        except Exception as e:
            return _error_response(str(e))

    # ------------------------------------------------------------------ #
    # Feature 2: Reboot device
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def reboot_device(
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Reboot the OpenWRT router.

        Requires ENABLE_WRITE_OPERATIONS=1 to be set.
        This will disconnect the SSH session. The router will be
        unreachable for approximately 60 seconds.

        Args:
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, action, note.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            check_write_enabled()
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            writer = get_writer(explorer.ssh)
            result = await writer.reboot_device()
            return _success_response(result, _meta=build_meta("reboot_device", _start))
        except ValidationError as e:
            return _error_response_extended(
                "INVALID_PARAM",
                str(e),
                False,
                suggestion="Set ENABLE_WRITE_OPERATIONS=1 to enable write tools.",
            )
        except Exception as e:
            return _error_response(str(e))

    # ------------------------------------------------------------------ #
    # Feature 3: Standalone diagnostic tools
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def ping_host(
        host: str,
        count: int = 4,
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Ping a host from the router.

        Args:
            host: Hostname or IP to ping (e.g., '8.8.8.8', 'google.com').
            count: Number of ping packets (1-10, default 4).
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, host, output, reachable.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.ping_host(host, count)
            return _success_response(result, _meta=build_meta("ping_host", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def traceroute_host(
        host: str,
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Traceroute to a host from the router.

        Args:
            host: Hostname or IP to trace (e.g., '8.8.8.8').
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, host, output.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.traceroute_host(host)
            return _success_response(result, _meta=build_meta("traceroute_host", _start))
        except Exception as e:
            return _error_response(str(e))

    @mcp.tool()
    async def nslookup_host(
        host: str,
        dns_server: str = "8.8.8.8",
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Look up DNS information for a hostname from the router.

        Args:
            host: Hostname to resolve (e.g., 'google.com').
            dns_server: DNS server to query (default '8.8.8.8').
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, host, resolved, output.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.nslookup_host(host, dns_server)
            return _success_response(result, _meta=build_meta("nslookup_host", _start))
        except Exception as e:
            return _error_response(str(e))

    # ------------------------------------------------------------------ #
    # Feature 4: WiFi survey
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def wifi_scan(
        radio: str = "wlan0",
        timeout_seconds: int = SSH_TIMEOUT,
    ) -> str:
        """Scan for neighboring WiFi networks.

        Args:
            radio: Radio interface to scan (default 'wlan0').
            timeout_seconds: Optional SSH timeout override (default uses SSH_TIMEOUT).

        Returns:
            JSON string with success, radio, networks_found, networks list.

        @since v1.2.0
        """
        _start = time.monotonic()
        set_request_id(generate_request_id())
        try:
            explorer = get_explorer()
            explorer.ssh.set_timeout(timeout_seconds)
            result = await explorer.wifi_scan(radio)
            return _success_response(result, _meta=build_meta("wifi_scan", _start))
        except Exception as e:
            return _error_response(str(e))

    # ------------------------------------------------------------------ #

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
        "get_router_context": _make_manifest("get_router_context", 30000, "slow"),
        "describe_router_capabilities": _make_manifest(
            "describe_router_capabilities", 3000, "instant"
        ),
        "restart_interface": _make_write_manifest("restart_interface", 20000, "moderate"),
        "reload_network": _make_write_manifest("reload_network", 20000, "moderate"),
        "uci_set": _make_write_manifest("uci_set", 15000, "moderate"),
        "uci_commit": _make_write_manifest("uci_commit", 15000, "moderate"),
        "reboot_device": _make_write_manifest("reboot_device", 30000, "slow"),
        "ping_host": _make_manifest("ping_host", 10000, "fast"),
        "traceroute_host": _make_manifest("traceroute_host", 30000, "slow"),
        "nslookup_host": _make_manifest("nslookup_host", 10000, "fast"),
        "wifi_scan": _make_manifest("wifi_scan", 15000, "moderate"),
    }
    try:
        tm = getattr(mcp, "_tool_manager", None)
        all_tools = getattr(mcp, "_tools", {}) or (getattr(tm, "_tools", {}) if tm else {})

        # FastMCP 3.x: tools aren't in _tools dict. Use list_tools instead.
        if not all_tools and hasattr(mcp, "list_tools"):
            try:
                ftools: list = asyncio.run(mcp.list_tools())
                all_tools = {}
                for ft in ftools:
                    name = getattr(ft, "name", None)
                    if name:
                        all_tools[name] = ft
            except Exception:
                pass

        for name, fn in all_tools.items():
            if name in tool_manifest_map:
                fn.__manifest__ = tool_manifest_map[name]
        _inject_risk_prefixes(all_tools, tool_manifest_map)
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
