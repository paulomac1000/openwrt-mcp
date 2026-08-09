"""Transport-independent OpenWRT read service backed by serialized SSH."""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any

from openwrt_mcp.settings import Settings, get_settings
from openwrt_mcp.tools.ssh_client import SSHConnection
from openwrt_mcp.validators import SecurityValidator, ValidationError

_ALLOWED_UCI_CONFIGS = frozenset(
    {
        "dhcp",
        "network",
        "wireless",
        "firewall",
        "system",
        "dropbear",
        "luci",
        "uhttpd",
        "rpcd",
        "ucitrack",
        "ubootenv",
    }
)


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
            return {
                "success": False,
                "status": "disconnected",
                "error": stderr or "SSH dependency unavailable",
                "host": self.settings.openwrt_host,
            }
        try:
            board = json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "success": False,
                "status": "unresponsive",
                "error": "Invalid board response",
                "host": self.settings.openwrt_host,
            }
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

        uptime_raw, uptime_error, uptime_code = await self._run("cat /proc/uptime")
        memory_raw, memory_error, memory_code = await self._run("cat /proc/meminfo")

        uptime_seconds: float | None = None
        if uptime_code == 0:
            try:
                uptime_seconds = float(uptime_raw.split()[0])
            except (ValueError, IndexError):
                pass
        uptime_ok = uptime_seconds is not None

        memory: dict[str, int] = {}
        if memory_code == 0:
            for line in memory_raw.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                match = re.search(r"\d+", value)
                if match:
                    memory[key] = int(match.group()) * 1024
        total = memory.get("MemTotal")
        free = memory.get("MemFree")
        memory_ok = total is not None and total > 0 and free is not None

        model = board.get("model", "unknown")
        if isinstance(model, dict):
            model = model.get("name") or model.get("id") or "unknown"
        return {
            "success": True,
            "partial": not (uptime_ok and memory_ok),
            "subsections": {
                "board": {"success": True, "error": None},
                "uptime": {
                    "success": uptime_ok,
                    "error": (
                        None
                        if uptime_ok
                        else uptime_error
                        or ("Invalid /proc/uptime response" if uptime_code == 0 else "Failed to read /proc/uptime")
                    ),
                },
                "memory": {
                    "success": memory_ok,
                    "error": (
                        None
                        if memory_ok
                        else memory_error
                        or ("Invalid /proc/meminfo response" if memory_code == 0 else "Failed to read /proc/meminfo")
                    ),
                },
            },
            "model": str(model),
            "hostname": board.get("hostname", "unknown"),
            "openwrt_version": board.get("release", {}).get("version", "unknown"),
            "kernel": board.get("kernel", "unknown"),
            "uptime_seconds": uptime_seconds,
            "uptime": self._format_uptime(int(uptime_seconds)) if uptime_seconds is not None else None,
            "memory_total_bytes": total if memory_ok else None,
            "memory_free_bytes": free if memory_ok else None,
            "memory_used_percent": (
                round((1 - free / total) * 100, 1)
                if memory_ok and total is not None and free is not None
                else None
            ),
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
                            "idle": station.get(
                                "inactive",
                                station.get("idle", 0),
                            ),
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
                interface_type = interface.get("type", "unknown")
                interfaces.append(
                    {
                        "radio": radio,
                        "type": interface_type,
                        "ssid": config.get("ssid", "unknown"),
                        "mode": config.get("mode", interface_type),
                        "ifname": interface.get(
                            "ifname",
                            interface.get("section", "unknown"),
                        ),
                        "clients_count": len(clients),
                        "clients": clients[:10],
                    }
                )
        return {
            "success": True,
            "interfaces_count": len(interfaces),
            "interfaces": interfaces,
            "note": (
                "Router may be in repeater mode (no AP interfaces)"
                if not any(item.get("type") == "ap" for item in interfaces)
                else None
            ),
        }

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
        return {
            "success": True,
            "leases_count": len(leases),
            "leases": leases[:50],
        }

    async def get_firewall_rules(self) -> dict[str, Any]:
        for command, kind in (
            ("nft list ruleset", "nftables"),
            ("fw4 status", "fw4"),
            ("iptables -L -n -v", "iptables"),
        ):
            raw, _, code = await self._run(command)
            if code == 0 and raw.strip():
                preview = "\n".join(
                    line
                    for line in raw.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                )
                return {
                    "success": True,
                    "firewall_type": kind,
                    "rules_preview": preview[:2_500],
                    "full_output_truncated": len(preview) > 2_500,
                }
        return {"success": False, "error": "No supported firewall output available"}

    async def read_uci_config(self, config_name: str) -> dict[str, Any]:
        config = SecurityValidator.validate_uci_config(config_name)
        if config not in _ALLOWED_UCI_CONFIGS:
            allowed = ", ".join(sorted(_ALLOWED_UCI_CONFIGS))
            raise ValidationError(f"Configuration {config!r} not supported. Allowed: {allowed}")
        raw, error, code = await self._run(f"uci show {config}")
        if code != 0:
            return {
                "success": False,
                "error": error or f"Configuration {config!r} does not exist",
            }
        entries: dict[str, str] = {}
        for line in raw.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                entries[key] = value.strip("'\"")
        return {
            "success": True,
            "config_name": config,
            "entries_count": len(entries),
            "sample": dict(list(entries.items())[:20]),
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
                    {
                        "name": name.strip(),
                        "version": version.strip() if separator else "unknown",
                    }
                )
        return {
            "success": True,
            "packages_count": len(packages),
            "packages_sample": packages[:20],
        }

    async def get_router_logs(
        self,
        lines: int = 50,
        filter_level: str = "all",
    ) -> dict[str, Any]:
        bounded = min(max(int(lines), 10), 200)
        raw, error, code = await self._run(f"logread -l {bounded}")
        if code != 0:
            return {"success": False, "error": error or "Failed to read logs"}
        values = raw.splitlines()
        if filter_level != "all":
            needle = filter_level.casefold()
            values = [line for line in values if needle in line.casefold()]
        selected = values[:bounded]
        return {
            "success": True,
            "lines_count": len(selected),
            "logs": "\n".join(selected)[:3_000],
        }

    async def search_router_logs(
        self,
        search_term: str,
        max_results: int = 30,
    ) -> dict[str, Any]:
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
            "results": "\n".join(matches[-bounded:])[:3_000],
        }

    async def diagnose_router_connectivity(self) -> dict[str, Any]:
        tests: dict[str, dict[str, Any]] = {}

        stdout, stderr, code = await self._run("ping -c 2 -W 2 8.8.8.8")
        tests["dns_google"] = {
            "success": code == 0,
            "output": (stdout or stderr)[:200],
        }

        stdout, stderr, code = await self._run("nslookup cloudflare.com 8.8.8.8")
        tests["internet_dns"] = {
            "success": code == 0 and ("Address" in stdout or "Name:" in stdout),
            "output": (stdout or stderr)[:200],
        }

        route_output, _, _ = await self._run("ip route show")
        gateway = self._default_gateway(route_output)
        if gateway:
            stdout, stderr, code = await self._run(f"ping -c 2 -W 1 {gateway}")
            tests["gateway"] = {
                "success": code == 0,
                "gateway_ip": gateway,
                "output": (stdout or stderr)[:200],
            }
        else:
            tests["gateway"] = {
                "success": False,
                "error": "No default gateway found in routing table",
            }

        stdout, stderr, code = await self._run("nslookup openwrt.lan 127.0.0.1")
        tests["local_dns"] = {
            "success": code == 0,
            "output": (stdout or stderr)[:200],
        }

        total = len(tests)
        passed = sum(1 for item in tests.values() if item["success"])
        health = "excellent" if passed == total else "good" if passed >= total - 1 else "poor"
        return {
            "success": True,
            "tests": tests,
            "summary": {
                "passed": passed,
                "failed": total - passed,
                "total": total,
                "health": health,
            },
        }

    async def get_dhcp_static_leases(self) -> dict[str, Any]:
        raw, error, code = await self._run("uci show dhcp")
        if code != 0:
            return {"success": False, "error": error or "Failed to read DHCP config"}

        sections: dict[str, dict[str, str]] = {}
        section_types: dict[str, str] = {}
        for line in raw.splitlines():
            if "=" not in line or not line.startswith("dhcp."):
                continue
            key, value = line.split("=", 1)
            relative = key[len("dhcp.") :]
            section, dot, option = relative.partition(".")
            cleaned = value.strip("'\"")
            if dot:
                sections.setdefault(section, {})[option] = cleaned
            else:
                section_types[section] = cleaned

        static_leases: list[dict[str, str]] = []
        for section, values in sections.items():
            if section_types.get(section) not in {None, "host"}:
                continue
            if not values.get("mac") and not values.get("ip"):
                continue
            lease: dict[str, str] = {}
            if values.get("mac"):
                lease["mac"] = values["mac"].lower()
            if values.get("ip"):
                lease["ip"] = values["ip"]
            hostname = values.get("name") or values.get("hostname")
            if hostname:
                lease["hostname"] = hostname
            static_leases.append(lease)
        return {
            "success": True,
            "static_leases_count": len(static_leases),
            "leases": static_leases,
        }

    async def search_dhcp_logs(self, search_term: str) -> dict[str, Any]:
        if not SecurityValidator.is_safe_search_term(search_term):
            raise ValidationError("Unsafe or invalid DHCP search phrase")
        raw, error, code = await self._run("logread -l 500")
        if code != 0:
            return {"success": False, "error": error or "Failed to read logs"}
        events = []
        term = search_term.casefold()
        for line in raw.splitlines():
            folded = line.casefold()
            if term not in folded or ("dhcp" not in folded and "dnsmasq" not in folded):
                continue
            events.append(
                {
                    "raw_log": line[:200],
                    "event_type": self._dhcp_event_type(line),
                    "contains_search_term": True,
                }
            )
        return {
            "success": True,
            "search_term": search_term,
            "events_found": len(events),
            "events": events[:50],
        }

    async def get_device_dhcp_details(
        self,
        mac_address: str | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        identifier = self._validate_device_identifier(mac_address, ip_address)
        leases = await self.list_dhcp_leases()
        static = await self.get_dhcp_static_leases()
        logs = await self.search_dhcp_logs(identifier)
        lease_ok = bool(leases.get("success"))
        static_ok = bool(static.get("success"))
        logs_ok = bool(logs.get("success"))
        if not lease_ok and not static_ok:
            return {
                "success": False,
                "error": "Unable to read DHCP lease or reservation sources",
            }

        folded = identifier.casefold()
        current = (
            next(
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
            if lease_ok
            else None
        )
        reservation = (
            next(
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
            if static_ok
            else None
        )
        return {
            "success": True,
            "partial": not (lease_ok and static_ok and logs_ok),
            "subsections": {
                "leases": self._subsection_status(leases),
                "static_reservations": self._subsection_status(static),
                "logs": self._subsection_status(logs),
            },
            "device_identifier": identifier,
            "current_lease": current,
            "static_reservation": reservation,
            "has_static_reservation": reservation is not None if static_ok else None,
            "is_currently_connected": current is not None if lease_ok else None,
            "recent_log_events": logs.get("events", [])[:5] if logs_ok else [],
            "note": "DHCP logs require 'log_dhcp' enabled in dnsmasq configuration.",
        }

    async def get_router_context(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": True,
            "device_id": "unknown",
            "model": "unknown",
            "uptime_seconds": None,
            "schema_version": "2.0",
            "subsections": {},
        }

        system = await self.get_system_info()
        if system.get("success"):
            result.update(
                {
                    "device_id": system.get("hostname", "unknown"),
                    "model": system.get("model", "unknown"),
                    "uptime_seconds": system.get("uptime_seconds"),
                    "memory_used_percent": system.get("memory_used_percent"),
                    "openwrt_version": system.get("openwrt_version", "unknown"),
                    "kernel": system.get("kernel", "unknown"),
                }
            )
        result["subsections"]["system"] = self._subsection_status(system)

        load_raw, load_error, load_code = await self._run("cat /proc/loadavg")
        try:
            result["cpu_load_1min"] = float(load_raw.split()[0])
            result["subsections"]["cpu"] = {"success": load_code == 0}
        except (ValueError, IndexError):
            result["cpu_load_1min"] = None
            result["subsections"]["cpu"] = {
                "success": False,
                "error": load_error or "loadavg_failed",
            }

        wifi = await self.get_wifi_status()
        if wifi.get("success"):
            interfaces = wifi.get("interfaces", [])
            result["interfaces_count"] = wifi.get("interfaces_count", 0)
            result["wifi_clients_total"] = sum(item.get("clients_count", 0) for item in interfaces)
            result["wifi_interfaces"] = [
                {
                    "ssid": item.get("ssid"),
                    "mode": item.get("mode"),
                    "clients": item.get("clients_count"),
                }
                for item in interfaces
            ]
        result["subsections"]["wifi"] = self._subsection_status(wifi)

        dhcp = await self.list_dhcp_leases()
        if dhcp.get("success"):
            result["dhcp_leases_count"] = dhcp.get("leases_count", 0)
        result["subsections"]["dhcp"] = self._subsection_status(dhcp)

        connectivity = await self.diagnose_router_connectivity()
        if connectivity.get("success"):
            result["connectivity_health"] = connectivity.get("summary", {}).get(
                "health",
                "unknown",
            )
            result["internet_reachable"] = bool(
                connectivity.get("tests", {}).get("dns_google", {}).get("success")
            )
        result["subsections"]["connectivity"] = self._subsection_status(connectivity)
        result["partial"] = not all(
            section.get("success", False) for section in result["subsections"].values()
        )
        return result

    async def ping_host(self, host: str, count: int = 4) -> dict[str, Any]:
        host = self._validate_host(host)
        bounded = min(max(int(count), 1), 10)
        stdout, stderr, code = await self._run(f"ping -c {bounded} -W 2 {host}")
        output = stdout[:500] if stdout else (stderr or "no output")
        result: dict[str, Any] = {
            "success": code == 0,
            "host": host,
            "output": output,
            "reachable": code == 0,
        }
        if code != 0:
            result["error"] = stderr or "Ping failed"
        return result

    async def traceroute_host(self, host: str) -> dict[str, Any]:
        host = self._validate_host(host)
        stdout, stderr, code = await self._run(f"traceroute -n {host}")
        output = stdout[:1_000] if stdout else (stderr or "traceroute not available")
        result: dict[str, Any] = {
            "success": code == 0,
            "host": host,
            "output": output,
        }
        if code != 0:
            result["error"] = stderr or "Traceroute failed"
        return result

    async def nslookup_host(
        self,
        host: str,
        dns_server: str = "8.8.8.8",
    ) -> dict[str, Any]:
        host = self._validate_host(host)
        dns_server = self._validate_host(dns_server)
        stdout, stderr, code = await self._run(f"nslookup {host} {dns_server}")
        resolved = code == 0 and ("Address" in stdout or "Name:" in stdout)
        result: dict[str, Any] = {
            "success": code == 0,
            "host": host,
            "resolved": resolved,
            "output": stdout[:500] if stdout else (stderr or "no output"),
        }
        if code != 0:
            result["error"] = stderr or "DNS lookup failed"
        return result

    async def wifi_scan(self, radio: str = "wlan0") -> dict[str, Any]:
        radio = SecurityValidator.validate_interface_name(radio)
        stdout, stderr, code = await self._run(f"iwinfo {radio} scan")
        if code != 0:
            return {"success": False, "error": stderr or "WiFi scan failed"}
        networks = self._parse_wifi_scan(stdout)
        return {
            "success": True,
            "radio": radio,
            "networks_found": len(networks),
            "networks": networks[:20],
        }

    @staticmethod
    def _parse_wifi_scan(raw: str) -> list[dict[str, Any]]:
        networks: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("Cell"):
                if current:
                    networks.append(current)
                current = {}
            if "Address:" in stripped:
                current["bssid"] = stripped.split("Address:", 1)[1].strip()
            if "ESSID:" in stripped:
                current["ssid"] = stripped.split("ESSID:", 1)[1].strip().strip('"')
            mode_match = re.search(r"(?:^|\s)Mode:\s*([^\s]+)", stripped)
            if mode_match:
                current["mode"] = mode_match.group(1)
            channel_match = re.search(r"(?:^|\s)Channel:\s*([^\s]+)", stripped)
            if channel_match:
                current["channel"] = channel_match.group(1)
            if "Signal level:" in stripped:
                current["signal"] = stripped.split("Signal level:", 1)[1].strip()
        if current:
            networks.append(current)
        return networks

    @staticmethod
    def _validate_host(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}",
            value,
        ):
            raise ValidationError("Invalid host or address")
        return value

    @staticmethod
    def _validate_device_identifier(
        mac_address: str | None,
        ip_address: str | None,
    ) -> str:
        if not mac_address and not ip_address:
            raise ValidationError("Provide device MAC or IP")
        if mac_address:
            normalized = mac_address.lower().replace("-", ":")
            if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", normalized):
                raise ValidationError("Invalid MAC address format")
            return normalized
        assert ip_address is not None
        try:
            return str(ipaddress.ip_address(ip_address))
        except ValueError as exc:
            raise ValidationError("Invalid IP address format") from exc

    @staticmethod
    def _default_gateway(route_output: str) -> str | None:
        for line in route_output.splitlines():
            parts = line.split()
            if "default" not in parts or "via" not in parts:
                continue
            index = parts.index("via")
            if index + 1 < len(parts):
                candidate = parts[index + 1]
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    return None
        return None

    @staticmethod
    def _subsection_status(value: dict[str, Any]) -> dict[str, Any]:
        success = bool(value.get("success")) and not bool(value.get("partial"))
        return {
            "success": success,
            "error": None if success else value.get("error") or ("partial result" if value.get("partial") else None),
        }

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        days, remainder = divmod(max(seconds, 0), 86_400)
        hours, remainder = divmod(remainder, 3_600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days} days, {hours:02}:{minutes:02}:{seconds:02}"

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
