"""Transport-independent OpenWRT read service backed by the serialized SSH adapter."""

from __future__ import annotations

import json
import re
from typing import Any

from openwrt_mcp.settings import Settings, get_settings
from openwrt_mcp.tools.ssh_client import SSHConnection
from openwrt_mcp.validators import SecurityValidator, ValidationError


class OpenWRTExplorer:
    """Bounded read operations for one configured router."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        ssh: SSHConnection | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.ssh = ssh or SSHConnection(self.settings)

    async def _run(self, command: str) -> tuple[str, str, int]:
        return await self.ssh.execute(command)

    async def test_connection(self) -> dict[str, Any]:
        stdout, stderr, code = await self._run("ubus call system board")
        if code != 0:
            return {"success": False, "error": stderr or "SSH dependency unavailable"}
        try:
            board = json.loads(stdout)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid board response"}
        model = board.get("model", "unknown")
        if isinstance(model, dict):
            model = model.get("name") or model.get("id") or "unknown"
        return {
            "success": True,
            "status": "connected",
            "host": self.settings.openwrt_host,
            "model": str(model),
            "release": board.get("release", {}).get("version", "unknown"),
        }

    async def get_system_info(self) -> dict[str, Any]:
        board_raw, error, code = await self._run("ubus call system board")
        if code != 0:
            return {"success": False, "error": error or "Failed to read system board"}
        try:
            board = json.loads(board_raw)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid board response"}
        uptime_raw, _, _ = await self._run("cat /proc/uptime")
        memory_raw, _, _ = await self._run("cat /proc/meminfo")
        try:
            uptime_seconds = float(uptime_raw.split()[0])
        except (ValueError, IndexError):
            uptime_seconds = 0.0
        memory: dict[str, int] = {}
        for line in memory_raw.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            match = re.search(r"\d+", value)
            if match:
                memory[key] = int(match.group()) * 1024
        total = memory.get("MemTotal", 0)
        available = memory.get("MemAvailable", memory.get("MemFree", 0))
        model = board.get("model", "unknown")
        if isinstance(model, dict):
            model = model.get("name") or model.get("id") or "unknown"
        return {
            "success": True,
            "model": str(model),
            "hostname": board.get("hostname", "unknown"),
            "openwrt_version": board.get("release", {}).get("version", "unknown"),
            "kernel": board.get("kernel", "unknown"),
            "uptime_seconds": uptime_seconds,
            "uptime": self._format_uptime(int(uptime_seconds)),
            "memory_total_bytes": total,
            "memory_free_bytes": available,
            "memory_used_percent": round((1 - available / total) * 100, 1) if total else 0,
        }

    async def get_wifi_status(self) -> dict[str, Any]:
        raw, error, code = await self._run("ubus call network.wireless status")
        if code != 0:
            return {"success": False, "error": error or "Failed to read Wi-Fi status"}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid Wi-Fi response"}
        interfaces: list[dict[str, Any]] = []
        for radio, radio_data in data.items():
            for interface in radio_data.get("interfaces", []):
                config = interface.get("config", {})
                clients: list[dict[str, Any]] = []
                for station in interface.get("stations", []):
                    clients.append(
                        {
                            "mac": station.get("mac", "unknown"),
                            "signal": station.get("signal", 0),
                            "idle": station.get("inactive", station.get("idle", 0)),
                        }
                    )
                for mac, station in interface.get("clients", {}).items():
                    clients.append(
                        {
                            "mac": mac,
                            "signal": station.get("signal", 0),
                            "idle": station.get("idle", 0),
                        }
                    )
                interfaces.append(
                    {
                        "radio": radio,
                        "type": interface.get("type", "unknown"),
                        "ssid": config.get("ssid", "unknown"),
                        "mode": config.get("mode", interface.get("type", "unknown")),
                        "ifname": interface.get("ifname", interface.get("section", "unknown")),
                        "clients_count": len(clients),
                        "clients": clients[:50],
                    }
                )
        return {"success": True, "interfaces_count": len(interfaces), "interfaces": interfaces}

    async def list_dhcp_leases(self) -> dict[str, Any]:
        raw, error, code = await self._run("cat /tmp/dhcp.leases")
        if code != 0:
            return {"success": False, "error": error or "Failed to read DHCP leases"}
        leases: list[dict[str, Any]] = []
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            leases.append(
                {
                    "expires_at": parts[0],
                    "mac": parts[1].lower(),
                    "ip": parts[2],
                    "hostname": None if parts[3] == "*" else parts[3],
                }
            )
        return {"success": True, "leases_count": len(leases), "leases": leases[:200]}

    async def get_firewall_rules(self) -> dict[str, Any]:
        for command, kind in (
            ("nft list ruleset", "nftables"),
            ("fw4 status", "fw4"),
            ("iptables -L -n -v", "iptables"),
        ):
            raw, _, code = await self._run(command)
            if code == 0 and raw.strip():
                preview = "\n".join(
                    line for line in raw.splitlines() if not line.lstrip().startswith("#")
                )
                return {
                    "success": True,
                    "firewall_type": kind,
                    "rules_preview": preview[:8_000],
                    "full_output_truncated": len(preview) > 8_000,
                }
        return {"success": False, "error": "No supported firewall output available"}

    async def read_uci_config(self, config_name: str) -> dict[str, Any]:
        config = SecurityValidator.validate_uci_config(config_name)
        allowed = {
            "dhcp", "network", "wireless", "firewall", "system", "dropbear",
            "luci", "uhttpd", "rpcd", "ucitrack", "ubootenv",
        }
        if config not in allowed:
            raise ValidationError(f"Unsupported UCI configuration: {config}")
        raw, error, code = await self._run(f"uci show {config}")
        if code != 0:
            return {"success": False, "error": error or "Failed to read UCI configuration"}
        entries: dict[str, str] = {}
        for line in raw.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                entries[key] = value.strip("'\"")
        return {
            "success": True,
            "config_name": config,
            "entries_count": len(entries),
            "sample": dict(list(entries.items())[:100]),
        }

    async def list_installed_packages(self) -> dict[str, Any]:
        raw, error, code = await self._run("opkg list-installed")
        if code != 0:
            return {"success": False, "error": error or "Failed to list packages"}
        packages: list[dict[str, str]] = []
        for line in raw.splitlines():
            name, separator, version = line.partition(" - ")
            if name.strip():
                packages.append(
                    {"name": name.strip(), "version": version.strip() if separator else "unknown"}
                )
        return {
            "success": True,
            "packages_count": len(packages),
            "packages_sample": packages[:100],
        }

    async def get_router_logs(self, lines: int = 50, filter_level: str = "all") -> dict[str, Any]:
        bounded = min(max(int(lines), 10), 200)
        raw, error, code = await self._run(f"logread -l {bounded}")
        if code != 0:
            return {"success": False, "error": error or "Failed to read logs"}
        values = raw.splitlines()
        if filter_level != "all":
            needle = filter_level.casefold()
            values = [line for line in values if needle in line.casefold()]
        text = "\n".join(values[:bounded])
        return {"success": True, "lines_count": len(values[:bounded]), "logs": text[:16_000]}

    async def search_router_logs(self, search_term: str, max_results: int = 30) -> dict[str, Any]:
        if not SecurityValidator.is_safe_search_term(search_term):
            raise ValidationError("Unsafe or invalid search phrase")
        raw, error, code = await self._run("logread -l 500")
        if code != 0:
            return {"success": False, "error": error or "Failed to read logs"}
        matches = [line for line in raw.splitlines() if search_term.casefold() in line.casefold()]
        bounded = min(max(int(max_results), 1), 100)
        return {
            "success": True,
            "search_term": search_term,
            "results_count": len(matches),
            "results": "\n".join(matches[-bounded:])[:16_000],
        }

    async def diagnose_router_connectivity(self) -> dict[str, Any]:
        tests: dict[str, dict[str, Any]] = {}
        for name, command in (
            ("internet_ip", "ping -c 2 -W 2 8.8.8.8"),
            ("internet_dns", "nslookup example.com 8.8.8.8"),
        ):
            stdout, stderr, code = await self._run(command)
            tests[name] = {"success": code == 0, "output": (stdout or stderr)[:500]}
        passed = sum(1 for item in tests.values() if item["success"])
        return {
            "success": True,
            "tests": tests,
            "summary": {
                "passed": passed,
                "failed": len(tests) - passed,
                "total": len(tests),
                "health": "healthy" if passed == len(tests) else "degraded",
            },
        }

    async def get_dhcp_static_leases(self) -> dict[str, Any]:
        raw, error, code = await self._run("uci show dhcp")
        if code != 0:
            return {"success": False, "error": error or "Failed to read DHCP config"}
        sections: dict[str, dict[str, str]] = {}
        for line in raw.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if not key.startswith("dhcp."):
                continue
            section, dot, option = key[len("dhcp."):].partition(".")
            if dot:
                sections.setdefault(section, {})[option] = value.strip("'\"")
        leases = [
            {
                "section": section,
                "mac": values.get("mac"),
                "ip": values.get("ip"),
                "hostname": values.get("name"),
            }
            for section, values in sections.items()
            if values.get("mac") or values.get("ip")
        ]
        return {"success": True, "static_leases_count": len(leases), "leases": leases[:200]}

    async def search_dhcp_logs(self, search_term: str) -> dict[str, Any]:
        if not SecurityValidator.is_safe_search_term(search_term):
            raise ValidationError("Unsafe or invalid DHCP search phrase")
        logs = await self.search_router_logs(search_term, 100)
        if not logs.get("success"):
            return logs
        events = [
            {"raw_log": line, "event_type": self._dhcp_event_type(line)}
            for line in str(logs.get("results", "")).splitlines()
            if "dhcp" in line.casefold() or "dnsmasq" in line.casefold()
        ]
        return {
            "success": True,
            "search_term": search_term,
            "events_found": len(events),
            "events": events,
        }

    async def get_device_dhcp_details(
        self, mac_address: str | None = None, ip_address: str | None = None
    ) -> dict[str, Any]:
        identifier = (mac_address or ip_address or "").strip()
        if not identifier or not SecurityValidator.is_safe_search_term(identifier):
            raise ValidationError("A valid MAC or IP address is required")
        leases = await self.list_dhcp_leases()
        static = await self.get_dhcp_static_leases()
        logs = await self.search_dhcp_logs(identifier)
        current = next(
            (
                item for item in leases.get("leases", [])
                if identifier.casefold()
                in {
                    str(item.get("mac", "")).casefold(),
                    str(item.get("ip", "")).casefold(),
                }
            ),
            None,
        )
        reservation = next(
            (
                item for item in static.get("leases", [])
                if identifier.casefold()
                in {
                    str(item.get("mac", "")).casefold(),
                    str(item.get("ip", "")).casefold(),
                }
            ),
            None,
        )
        return {
            "success": True,
            "device_identifier": identifier,
            "current_lease": current,
            "static_reservation": reservation,
            "has_static_reservation": reservation is not None,
            "is_currently_connected": current is not None,
            "recent_log_events": logs.get("events", [])[:50],
        }

    async def get_router_context(self) -> dict[str, Any]:
        system = await self.get_system_info()
        wifi = await self.get_wifi_status()
        dhcp = await self.list_dhcp_leases()
        connectivity = await self.diagnose_router_connectivity()
        return {
            "success": True,
            "device_id": (
                f"{self.settings.openwrt_user}@{self.settings.openwrt_host}:"
                f"{self.settings.openwrt_port}"
            ),
            "model": system.get("model", "unknown"),
            "uptime_seconds": system.get("uptime_seconds", 0),
            "subsections": {
                "system": system,
                "wifi": wifi,
                "dhcp": dhcp,
                "connectivity": connectivity,
            },
            "partial": not all(
                part.get("success") for part in (system, wifi, dhcp, connectivity)
            ),
        }

    async def ping_host(self, host: str, count: int = 4) -> dict[str, Any]:
        host = self._validate_host(host)
        bounded = min(max(int(count), 1), 5)
        stdout, stderr, code = await self._run(f"ping -c {bounded} -W 2 {host}")
        return {
            "success": code == 0,
            "host": host,
            "count": bounded,
            "output": (stdout or stderr)[:4_000],
        }

    async def traceroute_host(self, host: str) -> dict[str, Any]:
        host = self._validate_host(host)
        stdout, stderr, code = await self._run(f"traceroute -n {host}")
        return {"success": code == 0, "host": host, "output": (stdout or stderr)[:8_000]}

    async def nslookup_host(self, host: str, dns_server: str = "8.8.8.8") -> dict[str, Any]:
        host = self._validate_host(host)
        dns_server = self._validate_host(dns_server)
        stdout, stderr, code = await self._run(f"nslookup {host} {dns_server}")
        return {
            "success": code == 0,
            "host": host,
            "dns_server": dns_server,
            "output": (stdout or stderr)[:4_000],
        }

    async def wifi_scan(self, radio: str = "wlan0") -> dict[str, Any]:
        radio = SecurityValidator.validate_interface_name(radio)
        stdout, stderr, code = await self._run(f"iwinfo {radio} scan")
        return {"success": code == 0, "radio": radio, "output": (stdout or stderr)[:16_000]}

    @staticmethod
    def _validate_host(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", value
        ):
            raise ValidationError("Invalid host or address")
        return value

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        days, remainder = divmod(max(seconds, 0), 86_400)
        hours, remainder = divmod(remainder, 3_600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days} days, {hours:02}:{minutes:02}:{seconds:02}"

    @staticmethod
    def _dhcp_event_type(line: str) -> str:
        upper = line.upper()
        for event in ("DHCPACK", "DHCPREQUEST", "DHCPDISCOVER", "DHCPOFFER", "DHCPNAK"):
            if event in upper:
                return event.lower()
        return "dhcp"
