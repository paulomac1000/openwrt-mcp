"""Deterministic mock router used only when OPENWRT_MOCK_MODE=1."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class MockSSHConnection:
    @contextmanager
    def timeout_scope(self, seconds: int) -> Iterator[None]:
        if not 1 <= seconds <= 300:
            raise ValueError("invalid timeout")
        yield

    async def close(self) -> None:
        return None


class MockOpenWRTExplorer:
    """Stable no-I/O data set for local smoke tests and development."""

    def __init__(self) -> None:
        self.ssh = MockSSHConnection()

    async def test_connection(self) -> dict[str, Any]:
        return {
            "success": True,
            "status": "connected",
            "host": "mock-router.local",
            "model": "OpenWRT Mock Router",
            "release": "23.05-mock",
        }

    async def get_system_info(self) -> dict[str, Any]:
        return {
            "success": True,
            "model": "OpenWRT Mock Router",
            "hostname": "mock-router",
            "openwrt_version": "23.05-mock",
            "kernel": "6.6-mock",
            "uptime_seconds": 86_400,
            "uptime": "1 days, 00:00:00",
            "memory_total_bytes": 268_435_456,
            "memory_free_bytes": 134_217_728,
            "memory_used_percent": 50.0,
        }

    async def get_wifi_status(self) -> dict[str, Any]:
        return {
            "success": True,
            "interfaces_count": 1,
            "interfaces": [
                {
                    "radio": "radio0",
                    "type": "ap",
                    "ssid": "MockNetwork",
                    "mode": "ap",
                    "ifname": "wlan0",
                    "clients_count": 1,
                    "clients": [
                        {
                            "mac": "02:00:00:00:00:01",
                            "signal": -45,
                            "idle": 12,
                        }
                    ],
                }
            ],
            "note": None,
        }

    async def list_dhcp_leases(self) -> dict[str, Any]:
        return {
            "success": True,
            "leases_count": 1,
            "leases": [
                {
                    "expires_at": "1893456000",
                    "mac": "02:00:00:00:00:01",
                    "ip": "192.0.2.101",
                    "hostname": "mock-client",
                }
            ],
        }

    async def get_firewall_rules(self) -> dict[str, Any]:
        return {
            "success": True,
            "firewall_type": "nftables",
            "rules_preview": "table inet fw4 { # mock }",
            "full_output_truncated": False,
        }

    async def read_uci_config(self, config_name: str) -> dict[str, Any]:
        return {
            "success": True,
            "config_name": config_name,
            "entries_count": 1,
            "sample": {f"{config_name}.mock": "section"},
        }

    async def list_installed_packages(self) -> dict[str, Any]:
        return {
            "success": True,
            "packages_count": 2,
            "packages_sample": [
                {"name": "base-files", "version": "mock"},
                {"name": "busybox", "version": "mock"},
            ],
        }

    async def get_router_logs(
        self,
        lines: int,
        filter_level: str,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "lines_count": 1,
            "logs": f"mock log line ({filter_level}, requested={lines})",
        }

    async def search_router_logs(
        self,
        search_term: str,
        max_results: int,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "search_term": search_term,
            "results_count": 1,
            "results": f"mock result for {search_term}; max={max_results}",
        }

    async def diagnose_router_connectivity(self) -> dict[str, Any]:
        tests = {
            "dns_google": {"success": True, "output": "mock"},
            "internet_dns": {"success": True, "output": "mock"},
            "gateway": {
                "success": True,
                "gateway_ip": "192.0.2.1",
                "output": "mock",
            },
            "local_dns": {"success": True, "output": "mock"},
        }
        return {
            "success": True,
            "tests": tests,
            "summary": {
                "passed": 4,
                "failed": 0,
                "total": 4,
                "health": "excellent",
            },
        }

    async def get_dhcp_static_leases(self) -> dict[str, Any]:
        return {"success": True, "static_leases_count": 0, "leases": []}

    async def search_dhcp_logs(self, search_term: str) -> dict[str, Any]:
        return {
            "success": True,
            "search_term": search_term,
            "events_found": 1,
            "events": [
                {
                    "raw_log": f"DHCPACK for {search_term}",
                    "event_type": "ack",
                    "contains_search_term": True,
                }
            ],
        }

    async def get_device_dhcp_details(
        self,
        mac_address: str | None,
        ip_address: str | None,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "device_identifier": mac_address or ip_address,
            "current_lease": None,
            "static_reservation": None,
            "has_static_reservation": False,
            "is_currently_connected": False,
            "recent_log_events": [],
            "note": "DHCP logs require 'log_dhcp' enabled in dnsmasq configuration.",
        }

    async def get_router_context(self) -> dict[str, Any]:
        return {
            "success": True,
            "device_id": "mock-router",
            "model": "OpenWRT Mock Router",
            "uptime_seconds": 86_400,
            "schema_version": "1.0",
            "memory_used_percent": 50.0,
            "openwrt_version": "23.05-mock",
            "kernel": "6.6-mock",
            "cpu_load_1min": 0.1,
            "interfaces_count": 1,
            "wifi_clients_total": 1,
            "wifi_interfaces": [
                {"ssid": "MockNetwork", "mode": "ap", "clients": 1}
            ],
            "dhcp_leases_count": 1,
            "connectivity_health": "excellent",
            "internet_reachable": True,
            "subsections": {
                "system": {"success": True, "error": None},
                "cpu": {"success": True},
                "wifi": {"success": True, "error": None},
                "dhcp": {"success": True, "error": None},
                "connectivity": {"success": True, "error": None},
            },
            "partial": False,
        }

    async def ping_host(self, host: str, count: int) -> dict[str, Any]:
        return {
            "success": True,
            "host": host,
            "output": f"mock ping count={count}",
            "reachable": True,
        }

    async def traceroute_host(self, host: str) -> dict[str, Any]:
        return {
            "success": True,
            "host": host,
            "output": "1 192.0.2.1 1.0 ms",
        }

    async def nslookup_host(
        self,
        host: str,
        dns_server: str,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "host": host,
            "resolved": True,
            "output": f"Name: {host}\nAddress: 192.0.2.200\nServer: {dns_server}",
        }

    async def wifi_scan(self, radio: str) -> dict[str, Any]:
        return {
            "success": True,
            "radio": radio,
            "networks_found": 1,
            "networks": [
                {
                    "ssid": "MockNeighbor",
                    "channel": "6",
                    "signal": "-65 dBm",
                }
            ],
        }
