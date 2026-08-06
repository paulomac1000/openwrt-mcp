"""Public MCP registration backed by one invocation kernel."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openwrt_mcp import __version__
from openwrt_mcp.application import (
    CapabilityManifest,
    CapabilityRegistry,
    InvocationKernel,
    KernelError,
    ToolExecutionError,
)
from openwrt_mcp.settings import Settings


_WRITE_INACTIVE_REASON = (
    "Write capabilities are retained in the supported catalog but disabled until "
    "principal-bound, expiring approvals and authenticated Streamable HTTP are implemented."
)


def _read_manifest(
    name: str,
    *,
    confidentiality: str = "internal",
    timeout_ms: int = 15_000,
    cost: str = "cheap",
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version=__version__,
        risk="READ",
        side_effects="read",
        confidentiality=confidentiality,
        operational_impact="none",
        cost=cost,
        idempotent=True,
        retryable=True,
        concurrent_safe=False,
        timeout_ms=timeout_ms,
        requires_confirmation=False,
        reversible=True,
    )


def _inactive_write_manifest(name: str, *, destructive: bool = False) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version=__version__,
        risk="DESTRUCTIVE" if destructive else "WRITE",
        side_effects="destructive" if destructive else "write",
        confidentiality="internal",
        operational_impact="outage" if destructive else "persistent",
        cost="expensive" if destructive else "moderate",
        idempotent=False,
        retryable=False,
        concurrent_safe=False,
        timeout_ms=30_000 if destructive else 20_000,
        requires_confirmation=True,
        reversible=False,
        active=False,
        inactive_reason=_WRITE_INACTIVE_REASON,
    )


def build_manifest_registry() -> CapabilityRegistry:
    manifests = {
        "test_router_connection": _read_manifest("test_router_connection", timeout_ms=10_000),
        "get_router_info": _read_manifest("get_router_info"),
        "get_router_wifi_status": _read_manifest(
            "get_router_wifi_status", confidentiality="personal"
        ),
        "get_router_dhcp_leases": _read_manifest(
            "get_router_dhcp_leases", confidentiality="personal"
        ),
        "get_router_firewall_rules": _read_manifest(
            "get_router_firewall_rules", confidentiality="sensitive"
        ),
        "read_router_uci_config": _read_manifest(
            "read_router_uci_config", confidentiality="sensitive"
        ),
        "list_router_packages": _read_manifest("list_router_packages"),
        "get_router_logs": _read_manifest(
            "get_router_logs", confidentiality="sensitive", timeout_ms=30_000
        ),
        "search_router_logs": _read_manifest(
            "search_router_logs", confidentiality="sensitive", timeout_ms=30_000
        ),
        "diagnose_router_connectivity": _read_manifest(
            "diagnose_router_connectivity", timeout_ms=30_000, cost="moderate"
        ),
        "get_dhcp_static_leases": _read_manifest(
            "get_dhcp_static_leases", confidentiality="personal"
        ),
        "search_dhcp_logs": _read_manifest(
            "search_dhcp_logs", confidentiality="personal", timeout_ms=30_000
        ),
        "get_device_dhcp_details": _read_manifest(
            "get_device_dhcp_details", confidentiality="personal"
        ),
        "get_router_context": _read_manifest(
            "get_router_context", confidentiality="sensitive", timeout_ms=30_000
        ),
        "describe_router_capabilities": _read_manifest(
            "describe_router_capabilities", confidentiality="public", timeout_ms=3_000
        ),
        "ping_host": _read_manifest("ping_host", timeout_ms=10_000),
        "traceroute_host": _read_manifest("traceroute_host", timeout_ms=30_000),
        "nslookup_host": _read_manifest("nslookup_host", timeout_ms=10_000),
        "wifi_scan": _read_manifest(
            "wifi_scan", confidentiality="personal", timeout_ms=20_000
        ),
        "restart_interface": _inactive_write_manifest("restart_interface"),
        "reload_network": _inactive_write_manifest("reload_network"),
        "uci_set": _inactive_write_manifest("uci_set"),
        "uci_commit": _inactive_write_manifest("uci_commit"),
        "reboot_device": _inactive_write_manifest("reboot_device", destructive=True),
    }
    return CapabilityRegistry(manifests)


def build_invocation_kernel(settings: Settings, explorer: Any) -> InvocationKernel:
    registry = build_manifest_registry()

    async def call(
        method_name: str,
        *args: Any,
        timeout_seconds: int = settings.ssh_timeout,
    ) -> dict[str, Any]:
        method = getattr(explorer, method_name)
        with explorer.ssh.timeout_scope(timeout_seconds):
            return await method(*args)

    async def test_router_connection(timeout_seconds: int = settings.ssh_timeout) -> dict[str, Any]:
        return await call("test_connection", timeout_seconds=timeout_seconds)

    async def get_router_info(timeout_seconds: int = settings.ssh_timeout) -> dict[str, Any]:
        return await call("get_system_info", timeout_seconds=timeout_seconds)

    async def get_router_wifi_status(timeout_seconds: int = settings.ssh_timeout) -> dict[str, Any]:
        return await call("get_wifi_status", timeout_seconds=timeout_seconds)

    async def get_router_dhcp_leases(timeout_seconds: int = settings.ssh_timeout) -> dict[str, Any]:
        return await call("list_dhcp_leases", timeout_seconds=timeout_seconds)

    async def get_router_firewall_rules(
        timeout_seconds: int = settings.ssh_timeout,
    ) -> dict[str, Any]:
        return await call("get_firewall_rules", timeout_seconds=timeout_seconds)

    async def read_router_uci_config(
        config_name: str, timeout_seconds: int = settings.ssh_timeout
    ) -> dict[str, Any]:
        return await call("read_uci_config", config_name, timeout_seconds=timeout_seconds)

    async def list_router_packages(timeout_seconds: int = settings.ssh_timeout) -> dict[str, Any]:
        return await call("list_installed_packages", timeout_seconds=timeout_seconds)

    async def get_router_logs(
        lines: int = 50,
        filter_level: str = "all",
        timeout_seconds: int = settings.ssh_timeout,
    ) -> dict[str, Any]:
        return await call("get_router_logs", lines, filter_level, timeout_seconds=timeout_seconds)

    async def search_router_logs(
        search_term: str,
        max_results: int = 30,
        timeout_seconds: int = settings.ssh_timeout,
    ) -> dict[str, Any]:
        return await call(
            "search_router_logs", search_term, max_results, timeout_seconds=timeout_seconds
        )

    async def diagnose_router_connectivity(
        timeout_seconds: int = settings.ssh_timeout,
    ) -> dict[str, Any]:
        return await call("diagnose_router_connectivity", timeout_seconds=timeout_seconds)

    async def get_dhcp_static_leases(
        timeout_seconds: int = settings.ssh_timeout,
    ) -> dict[str, Any]:
        return await call("get_dhcp_static_leases", timeout_seconds=timeout_seconds)

    async def search_dhcp_logs(
        search_term: str, timeout_seconds: int = settings.ssh_timeout
    ) -> dict[str, Any]:
        return await call("search_dhcp_logs", search_term, timeout_seconds=timeout_seconds)

    async def get_device_dhcp_details(
        mac_address: str | None = None,
        ip_address: str | None = None,
        timeout_seconds: int = settings.ssh_timeout,
    ) -> dict[str, Any]:
        return await call(
            "get_device_dhcp_details",
            mac_address,
            ip_address,
            timeout_seconds=timeout_seconds,
        )

    async def get_router_context(timeout_seconds: int = settings.ssh_timeout) -> dict[str, Any]:
        return await call("get_router_context", timeout_seconds=timeout_seconds)

    async def ping_host(
        host: str, count: int = 4, timeout_seconds: int = settings.ssh_timeout
    ) -> dict[str, Any]:
        return await call("ping_host", host, count, timeout_seconds=timeout_seconds)

    async def traceroute_host(
        host: str, timeout_seconds: int = settings.ssh_timeout
    ) -> dict[str, Any]:
        return await call("traceroute_host", host, timeout_seconds=timeout_seconds)

    async def nslookup_host(
        host: str,
        dns_server: str = "8.8.8.8",
        timeout_seconds: int = settings.ssh_timeout,
    ) -> dict[str, Any]:
        return await call("nslookup_host", host, dns_server, timeout_seconds=timeout_seconds)

    async def wifi_scan(
        radio: str = "wlan0", timeout_seconds: int = settings.ssh_timeout
    ) -> dict[str, Any]:
        return await call("wifi_scan", radio, timeout_seconds=timeout_seconds)

    async def describe_router_capabilities() -> dict[str, Any]:
        supported = registry.supported()
        active = registry.active()
        return {
            "success": True,
            "server": "OpenWRT-Observer",
            "version": __version__,
            "schema_version": "2",
            "transports": ["stdio"],
            "supported_tools": supported,
            "active_tools": active,
            "total_supported": len(supported),
            "total_active": len(active),
        }

    operations = {
        "test_router_connection": test_router_connection,
        "get_router_info": get_router_info,
        "get_router_wifi_status": get_router_wifi_status,
        "get_router_dhcp_leases": get_router_dhcp_leases,
        "get_router_firewall_rules": get_router_firewall_rules,
        "read_router_uci_config": read_router_uci_config,
        "list_router_packages": list_router_packages,
        "get_router_logs": get_router_logs,
        "search_router_logs": search_router_logs,
        "diagnose_router_connectivity": diagnose_router_connectivity,
        "get_dhcp_static_leases": get_dhcp_static_leases,
        "search_dhcp_logs": search_dhcp_logs,
        "get_device_dhcp_details": get_device_dhcp_details,
        "get_router_context": get_router_context,
        "describe_router_capabilities": describe_router_capabilities,
        "ping_host": ping_host,
        "traceroute_host": traceroute_host,
        "nslookup_host": nslookup_host,
        "wifi_scan": wifi_scan,
    }
    return InvocationKernel(
        registry=registry,
        operations=operations,
        target_identity=(
            f"ssh:{settings.openwrt_user}@{settings.openwrt_host}:"
            f"{settings.openwrt_port}"
        ),
    )


def _attach_and_register(mcp: Any, fn: Callable[..., Any], manifest: CapabilityManifest) -> None:
    risk_prefix = f"[{manifest.risk}]"
    doc = (fn.__doc__ or fn.__name__.replace("_", " ")).strip()
    fn.__doc__ = f"{risk_prefix} {doc}"
    fn.__manifest__ = manifest.as_dict()  # type: ignore[attr-defined]
    registered = mcp.tool()(fn)
    try:
        registered.__manifest__ = manifest.as_dict()
    except (AttributeError, TypeError):
        pass


def _public_arguments(values: dict[str, Any]) -> dict[str, Any]:
    """Remove closure/internal names from wrapper-local argument mappings."""
    return {key: value for key, value in values.items() if key not in {"kernel"}}


async def _invoke_for_mcp(
    kernel: InvocationKernel, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    result = await kernel.invoke(name, arguments)
    if not result.success:
        if result.error is None:
            raise ToolExecutionError(
                KernelError(code="INTERNAL", message="Unknown tool failure")
            )
        raise ToolExecutionError(result.error)
    return result.as_dict()


def register_openwrt_tools(mcp: Any, kernel: InvocationKernel) -> None:
    """Register active tools; all wrappers delegate to the same kernel."""

    async def test_router_connection(timeout_seconds: int = 30) -> dict[str, Any]:
        """Test SSH connectivity to the configured router."""
        return await _invoke_for_mcp(kernel, "test_router_connection", _public_arguments(locals()))

    async def get_router_info(timeout_seconds: int = 30) -> dict[str, Any]:
        """Fetch router system information."""
        return await _invoke_for_mcp(kernel, "get_router_info", _public_arguments(locals()))

    async def get_router_wifi_status(timeout_seconds: int = 30) -> dict[str, Any]:
        """Fetch Wi-Fi interfaces and connected clients."""
        return await _invoke_for_mcp(kernel, "get_router_wifi_status", _public_arguments(locals()))

    async def get_router_dhcp_leases(timeout_seconds: int = 30) -> dict[str, Any]:
        """Fetch active DHCP leases."""
        return await _invoke_for_mcp(kernel, "get_router_dhcp_leases", _public_arguments(locals()))

    async def get_router_firewall_rules(timeout_seconds: int = 30) -> dict[str, Any]:
        """Fetch bounded firewall rule output."""
        return await _invoke_for_mcp(
            kernel, "get_router_firewall_rules", _public_arguments(locals())
        )

    async def read_router_uci_config(
        config_name: str, timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Read an allowlisted UCI configuration namespace."""
        return await _invoke_for_mcp(kernel, "read_router_uci_config", _public_arguments(locals()))

    async def list_router_packages(timeout_seconds: int = 30) -> dict[str, Any]:
        """List a bounded sample of installed packages."""
        return await _invoke_for_mcp(kernel, "list_router_packages", _public_arguments(locals()))

    async def get_router_logs(
        lines: int = 50, filter_level: str = "all", timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Fetch a bounded router log window."""
        return await _invoke_for_mcp(kernel, "get_router_logs", _public_arguments(locals()))

    async def search_router_logs(
        search_term: str, max_results: int = 30, timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Search router logs using Python-side filtering."""
        return await _invoke_for_mcp(kernel, "search_router_logs", _public_arguments(locals()))

    async def diagnose_router_connectivity(
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """Run bounded connectivity diagnostics from the router."""
        return await _invoke_for_mcp(
            kernel, "diagnose_router_connectivity", _public_arguments(locals())
        )

    async def get_dhcp_static_leases(timeout_seconds: int = 30) -> dict[str, Any]:
        """Fetch static DHCP reservations."""
        return await _invoke_for_mcp(kernel, "get_dhcp_static_leases", _public_arguments(locals()))

    async def search_dhcp_logs(
        search_term: str, timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Search DHCP-related router events."""
        return await _invoke_for_mcp(kernel, "search_dhcp_logs", _public_arguments(locals()))

    async def get_device_dhcp_details(
        mac_address: str | None = None,
        ip_address: str | None = None,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """Fetch lease, reservation, and recent event details for one device."""
        return await _invoke_for_mcp(kernel, "get_device_dhcp_details", _public_arguments(locals()))

    async def get_router_context(timeout_seconds: int = 30) -> dict[str, Any]:
        """Fetch a bounded aggregate router context snapshot."""
        return await _invoke_for_mcp(kernel, "get_router_context", _public_arguments(locals()))

    async def describe_router_capabilities() -> dict[str, Any]:
        """Describe supported and active catalogs without router I/O."""
        return await _invoke_for_mcp(kernel, "describe_router_capabilities", {})

    async def ping_host(
        host: str, count: int = 4, timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Ping a validated host from the router."""
        return await _invoke_for_mcp(kernel, "ping_host", _public_arguments(locals()))

    async def traceroute_host(
        host: str, timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Trace a validated host from the router."""
        return await _invoke_for_mcp(kernel, "traceroute_host", _public_arguments(locals()))

    async def nslookup_host(
        host: str, dns_server: str = "8.8.8.8", timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Resolve a host through a validated DNS server."""
        return await _invoke_for_mcp(kernel, "nslookup_host", _public_arguments(locals()))

    async def wifi_scan(
        radio: str = "wlan0", timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """Scan nearby Wi-Fi networks through an allowlisted interface."""
        return await _invoke_for_mcp(kernel, "wifi_scan", _public_arguments(locals()))

    functions = [
        test_router_connection,
        get_router_info,
        get_router_wifi_status,
        get_router_dhcp_leases,
        get_router_firewall_rules,
        read_router_uci_config,
        list_router_packages,
        get_router_logs,
        search_router_logs,
        diagnose_router_connectivity,
        get_dhcp_static_leases,
        search_dhcp_logs,
        get_device_dhcp_details,
        get_router_context,
        describe_router_capabilities,
        ping_host,
        traceroute_host,
        nslookup_host,
        wifi_scan,
    ]
    for fn in functions:
        manifest = kernel.registry.get(fn.__name__)
        if not manifest.active:
            raise RuntimeError(f"attempted to register inactive capability: {fn.__name__}")
        _attach_and_register(mcp, fn, manifest)
