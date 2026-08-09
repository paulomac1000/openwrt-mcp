"""Deterministic mock router used only when OPENWRT_MOCK_MODE=1."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from openwrt_mcp.validators import SecurityValidator, ValidationError


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
            "partial": False,
            "subsections": {
                "board": {"success": True, "error": None},
                "uptime": {"success": True, "error": None},
                "memory": {"success": True, "error": None},
            },
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
        config = SecurityValidator.validate_readable_uci_config(config_name)
        sample = self._uci_sample(config)
        return {
            "success": True,
            "config_name": config,
            "entries_count": len(sample),
            "sample": sample,
        }

    async def list_installed_packages(self) -> dict[str, Any]:
        return {
            "success": True,
            "packages_count": 3,
            "packages_sample": [
                {"name": "base-files", "version": "237-r23838-5eb723af07"},
                {"name": "busybox", "version": "1.36.1-2"},
                {"name": "dnsmasq-full", "version": "2.90-1"},
            ],
        }

    async def get_router_logs(
        self,
        lines: int,
        filter_level: str,
    ) -> dict[str, Any]:
        bounded = min(max(int(lines), 10), 200)
        entries = self._log_entries()
        if filter_level != "all":
            needle = filter_level.casefold()
            entries = [entry for entry in entries if needle in entry.casefold()]
        selected = entries[:bounded]
        return {
            "success": True,
            "lines_count": len(selected),
            "logs": "\n".join(selected)[:3_000],
        }

    async def search_router_logs(
        self,
        search_term: str,
        max_results: int,
    ) -> dict[str, Any]:
        if not SecurityValidator.is_safe_search_term(search_term):
            raise ValidationError("Unsafe or invalid search phrase")
        matches = [
            entry for entry in self._log_entries() if search_term.casefold() in entry.casefold()
        ]
        bounded = min(max(int(max_results), 1), 100)
        return {
            "success": True,
            "search_term": search_term,
            "results_count": len(matches),
            "results": "\n".join(matches[-bounded:])[:3_000],
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
        if not SecurityValidator.is_safe_search_term(search_term):
            raise ValidationError("Unsafe or invalid DHCP search phrase")
        term = search_term.casefold()
        events = [event for event in self._dhcp_events() if term in event["raw_log"].casefold()]
        return {
            "success": True,
            "search_term": search_term,
            "events_found": len(events),
            "events": events[:50],
        }

    async def get_device_dhcp_details(
        self,
        mac_address: str | None,
        ip_address: str | None,
    ) -> dict[str, Any]:
        identifier = SecurityValidator.validate_device_identifier(mac_address, ip_address)
        folded = identifier.casefold()
        leases = await self.list_dhcp_leases()
        current = next(
            (
                item
                for item in leases.get("leases", [])
                if folded
                in {
                    str(item.get("mac", "")).casefold(),
                    str(item.get("ip", "")).casefold(),
                }
            ),
            None,
        )
        static = await self.get_dhcp_static_leases()
        reservation = next(
            (
                item
                for item in static.get("leases", [])
                if folded
                in {
                    str(item.get("mac", "")).casefold(),
                    str(item.get("ip", "")).casefold(),
                }
            ),
            None,
        )
        events = [event for event in self._dhcp_events() if folded in event["raw_log"].casefold()]
        return {
            "success": True,
            "partial": False,
            "subsections": {
                "leases": {"success": True, "error": None},
                "static_reservations": {"success": True, "error": None},
                "logs": {"success": True, "error": None},
            },
            "device_identifier": identifier,
            "current_lease": current,
            "static_reservation": reservation,
            "has_static_reservation": reservation is not None,
            "is_currently_connected": current is not None,
            "recent_log_events": events[:5],
            "note": "DHCP logs require 'log_dhcp' enabled in dnsmasq configuration.",
        }

    async def get_router_context(self) -> dict[str, Any]:
        return {
            "success": True,
            "device_id": "mock-router",
            "model": "OpenWRT Mock Router",
            "uptime_seconds": 86_400,
            "schema_version": "2.0",
            "memory_used_percent": 50.0,
            "openwrt_version": "23.05-mock",
            "kernel": "6.6-mock",
            "cpu_load_1min": 0.1,
            "interfaces_count": 1,
            "wifi_clients_total": 1,
            "wifi_interfaces": [{"ssid": "MockNetwork", "mode": "ap", "clients": 1}],
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
        validated = SecurityValidator.validate_host_or_address(host)
        bounded = min(max(int(count), 1), 10)
        output = (
            f"PING {validated} (192.0.2.1) 56(84) bytes of data.\n"
            f"64 bytes from 192.0.2.1: icmp_seq=1 ttl=64 time=0.8 ms\n"
            f"64 bytes from 192.0.2.1: icmp_seq=2 ttl=64 time=0.6 ms\n"
            f"\n--- {validated} ping statistics ---\n"
            f"{bounded} packets transmitted, {bounded} received, 0% packet loss, "
            f"time {bounded * 5}ms\n"
            f"rtt min/avg/max/mdev = 0.5/0.7/0.8/0.1 ms"
        )
        return {
            "success": True,
            "host": validated,
            "output": output,
            "reachable": True,
        }

    async def traceroute_host(self, host: str) -> dict[str, Any]:
        validated = SecurityValidator.validate_host_or_address(host)
        output = (
            f"traceroute to {validated} (192.0.2.200), 30 hops max, 60 byte packets\n"
            f" 1  192.0.2.1  1.0 ms  0.9 ms  1.1 ms\n"
            f" 2  192.0.2.200  12.3 ms  12.5 ms  12.4 ms"
        )
        return {
            "success": True,
            "host": validated,
            "output": output,
        }

    async def nslookup_host(
        self,
        host: str,
        dns_server: str,
    ) -> dict[str, Any]:
        validated_host = SecurityValidator.validate_host_or_address(host)
        validated_dns = SecurityValidator.validate_host_or_address(dns_server)
        return {
            "success": True,
            "host": validated_host,
            "resolved": True,
            "output": (f"Name: {validated_host}\nAddress: 192.0.2.200\nServer: {validated_dns}"),
        }

    async def wifi_scan(self, radio: str) -> dict[str, Any]:
        validated_radio = SecurityValidator.validate_interface_name(radio)
        return {
            "success": True,
            "radio": validated_radio,
            "networks_found": 1,
            "networks": [
                {
                    "bssid": "02:00:00:00:00:01",
                    "ssid": "MockNeighbor",
                    "channel": "6",
                    "signal": "-65 dBm",
                    "mode": "Master",
                }
            ],
        }

    @staticmethod
    def _uci_sample(config_name: str) -> dict[str, str]:
        """Realistic ``uci show <config>`` key=value pairs for the mock router."""
        samples: dict[str, dict[str, str]] = {
            "network": {
                "network.loopback": "interface",
                "network.loopback.ifname": "lo",
                "network.loopback.proto": "static",
                "network.loopback.ipaddr": "127.0.0.1",
                "network.loopback.netmask": "255.0.0.0",
                "network.lan": "interface",
                "network.lan.proto": "static",
                "network.lan.ipaddr": "192.0.2.1",
                "network.lan.netmask": "255.255.255.0",
                "network.lan.device": "br-lan",
                "network.wan": "interface",
                "network.wan.proto": "dhcp",
                "network.wan.device": "eth1",
            },
            "dhcp": {
                "dhcp.lan": "dhcp",
                "dhcp.lan.interface": "lan",
                "dhcp.lan.start": "100",
                "dhcp.lan.limit": "150",
                "dhcp.lan.leasetime": "12h",
                "dhcp.lan.dhcpv4": "server",
                "dhcp.lan.dhcpv6": "server",
                "dhcp.odhcpd": "odhcpd",
                "dhcp.odhcpd.maindhcp": "1",
                "dhcp.odhcpd.leasefile": "/tmp/hosts/odhcpd",
            },
            "wireless": {
                "wireless.radio0": "wifi-device",
                "wireless.radio0.type": "mac80211",
                "wireless.radio0.channel": "6",
                "wireless.radio0.htmode": "HE40",
                "wireless.radio0.country": "PL",
                "wireless.default_radio0": "wifi-iface",
                "wireless.default_radio0.device": "radio0",
                "wireless.default_radio0.network": "lan",
                "wireless.default_radio0.mode": "ap",
                "wireless.default_radio0.ssid": "MockNetwork",
                "wireless.default_radio0.encryption": "sae",
            },
            "firewall": {
                "firewall.@zone[0]": "zone",
                "firewall.@zone[0].name": "lan",
                "firewall.@zone[0].input": "ACCEPT",
                "firewall.@zone[0].output": "ACCEPT",
                "firewall.@zone[0].forward": "ACCEPT",
                "firewall.@zone[1]": "zone",
                "firewall.@zone[1].name": "wan",
                "firewall.@zone[1].input": "REJECT",
                "firewall.@zone[1].output": "ACCEPT",
                "firewall.@zone[1].forward": "REJECT",
                "firewall.@zone[1].masq": "1",
                "firewall.@forwarding[0]": "forwarding",
                "firewall.@forwarding[0].src": "lan",
                "firewall.@forwarding[0].dest": "wan",
            },
            "system": {
                "system.@system[0]": "system",
                "system.@system[0].hostname": "mock-router",
                "system.@system[0].timezone": "CET-1CEST,M3.5.0,M10.5.0/3",
                "system.@system[0].ttylogin": "0",
            },
            "dropbear": {
                "dropbear.@dropbear[0]": "dropbear",
                "dropbear.@dropbear[0].PasswordAuth": "on",
                "dropbear.@dropbear[0].RootPasswordAuth": "on",
                "dropbear.@dropbear[0].Port": "22",
            },
        }
        fallback = {f"{config_name}.mock": "section"}
        return samples.get(config_name, fallback)

    @staticmethod
    def _log_entries() -> list[str]:
        """Realistic ``logread`` output lines for the mock router."""
        return [
            "Sun Aug  9 10:00:00 2026 daemon.info dnsmasq[1234]: read /etc/hosts - 5 addresses",
            "Sun Aug  9 10:00:00 2026 daemon.info dnsmasq-dhcp[1234]: DHCPACK(br-lan) 192.0.2.101 "
            "02:00:00:00:00:01 mock-client",
            "Sun Aug  9 10:00:01 2026 daemon.info dnsmasq-dhcp[1234]: DHCPREQUEST(br-lan) "
            "192.0.2.101 02:00:00:00:00:01",
            "Sun Aug  9 10:00:02 2026 daemon.info odhcpd[456]: DHCPv6 REQUEST from "
            "02:00:00:00:00:01",
            "Sun Aug  9 10:00:03 2026 kern.info kernel: br-lan: port 1(eth0) "
            "entered blocking state",
            "Sun Aug  9 10:00:04 2026 user.notice firewall: Reloading firewall "
            "due to ifup of 'wan'",
            "Sun Aug  9 10:00:05 2026 daemon.info procd: - init complete -",
        ]

    @classmethod
    def _dhcp_events(cls) -> list[dict[str, Any]]:
        """Dnsmasq DHCP events consistent with the mock lease table."""
        events: list[dict[str, Any]] = []
        for line in cls._log_entries():
            folded = line.casefold()
            if "dhcp" not in folded and "dnsmasq" not in folded:
                continue
            events.append(
                {
                    "raw_log": line[:200],
                    "event_type": cls._dhcp_event_type(line),
                    "contains_search_term": True,
                }
            )
        return events

    @staticmethod
    def _dhcp_event_type(line: str) -> str:
        upper = line.upper()
        mapping = {
            "DHCPACK": "ack",
            "DHCPREQUEST": "request",
            "DHCPDISCOVER": "discover",
            "DHCPOFFER": "offer",
            "DHCPNAK": "nak",
            "DHCPRELEASE": "release",
        }
        for marker, event_type in mapping.items():
            if marker in upper:
                return event_type
        return "unknown"
