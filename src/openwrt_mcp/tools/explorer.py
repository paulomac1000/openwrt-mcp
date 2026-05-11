"""
OpenWRT Router Explorer - internal functions for remote read-only access to OpenWRT over SSH.
All operations are read-only to avoid system modification risk.
"""

import json
import re
from typing import Any

from openwrt_mcp.tools.constants import (
    OPENWRT_HOST,
)
from openwrt_mcp.tools.response_helpers import _error_dict_extended
from openwrt_mcp.tools.ssh_client import SSHConnection
from openwrt_mcp.validators import SecurityValidator, ValidationError

# Design note: OpenWRTExplorer methods (get_system_info, list_dhcp_leases, etc.)
# serve as internal functions in the two-layer MCP pattern (L1+ standard).
# They are public because they are called from both MCP tool wrappers and
# other internal methods (e.g., get_device_dhcp_details calls list_dhcp_leases).
# The underscore prefix is omitted intentionally to avoid false "private method"
# signals in a class that is effectively a service layer shared across tools.


class OpenWRTExplorer:
    """Safe communication with OpenWRT router over SSH (read-only)."""

    def __init__(self) -> None:
        self.ssh = SSHConnection()
        self._connected = False

    async def test_connection(self) -> dict[str, Any]:
        """Test SSH connectivity to the router."""
        if not self._connected:
            self._connected = await self.ssh.connect()

        if not self._connected:
            return {
                "success": False,
                "status": "disconnected",
                "error": "Failed to establish SSH connection",
                "host": OPENWRT_HOST,
            }

        stdout, stderr, code = await self.ssh.execute("ubus call system board")
        if code == 0:
            try:
                board_info = json.loads(stdout)
                # Handle different model field formats (string or dict)
                model_data = board_info.get("model", "unknown")
                if isinstance(model_data, dict):
                    model = model_data.get("name", model_data.get("id", "unknown"))
                else:
                    model = str(model_data)
                return {
                    "success": True,
                    "status": "connected",
                    "host": OPENWRT_HOST,
                    "model": model,
                    "release": board_info.get("release", {}).get("version", "unknown"),
                }
            except json.JSONDecodeError:
                pass

        return {
            "success": False,
            "status": "unresponsive",
            "error": f"Router not responding: {stderr or 'no data'}",
        }

    async def get_system_info(self) -> dict[str, Any]:
        """Fetch basic system information."""
        stdout, stderr, code = await self.ssh.execute("ubus call system board")
        if code != 0:
            return {
                "success": False,
                "error": stderr or "Failed to fetch system information",
            }

        try:
            board = json.loads(stdout)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}

        stdout_uptime, _, _ = await self.ssh.execute("cat /proc/uptime")
        uptime_seconds = float(stdout_uptime.split()[0]) if stdout_uptime.strip() else 0

        stdout_mem, _, _ = await self.ssh.execute("cat /proc/meminfo")
        mem_total = mem_free = 0
        for line in stdout_mem.splitlines():
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) * 1024
            elif line.startswith("MemFree:"):
                mem_free = int(line.split()[1]) * 1024

        # Handle different model field formats (string or dict)
        model_data = board.get("model", "unknown")
        if isinstance(model_data, dict):
            model = model_data.get("name", model_data.get("id", "unknown"))
        else:
            model = str(model_data)

        return {
            "success": True,
            "model": model,
            "hostname": board.get("hostname", "unknown"),
            "openwrt_version": board.get("release", {}).get("version", "unknown"),
            "kernel": board.get("kernel", "unknown"),
            "uptime_seconds": uptime_seconds,
            "uptime": self._format_uptime(int(uptime_seconds)),
            "memory_total_bytes": mem_total,
            "memory_free_bytes": mem_free,
            "memory_used_percent": round((1 - mem_free / mem_total) * 100, 1) if mem_total else 0,
        }

    async def get_wifi_status(self) -> dict[str, Any]:
        """Fetch WiFi status and connected clients (supports AP and STA)."""
        stdout, stderr, code = await self.ssh.execute("ubus call network.wireless status")
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch WiFi status"}

        try:
            data = json.loads(stdout)
            interfaces = []

            for radio, cfg in data.items():
                radio_interfaces = cfg.get("interfaces", [])

                for iface in radio_interfaces:
                    iface_type = iface.get("type", "unknown")
                    config = iface.get("config", {})

                    # Collect clients (different formats in different versions)
                    clients = []

                    # format 1: stations array
                    for station in iface.get("stations", []):
                        clients.append(
                            {
                                "mac": station.get("mac", "unknown"),
                                "signal": station.get("signal", 0),
                                "idle": station.get("inactive", station.get("idle", 0)),
                            }
                        )

                    # format 2: clients dict (older versions)
                    for mac, client in iface.get("clients", {}).items():
                        clients.append(
                            {
                                "mac": mac,
                                "signal": client.get("signal", 0),
                                "idle": client.get("idle", 0),
                            }
                        )

                    interfaces.append(
                        {
                            "radio": radio,
                            "type": iface_type,
                            "ssid": config.get("ssid", "unknown"),
                            "mode": config.get("mode", iface_type),
                            "ifname": iface.get("ifname", iface.get("section", "unknown")),
                            "clients_count": len(clients),
                            "clients": clients[:10],
                        }
                    )

            return {
                "success": True,
                "interfaces_count": len(interfaces),
                "interfaces": interfaces,
                "note": "Router may be in repeater mode (no AP interfaces)"
                if not any(i.get("type") == "ap" for i in interfaces)
                else None,
            }
        except Exception as e:
            return {"success": False, "error": f"Parse error: {str(e)}"}

    async def list_dhcp_leases(self) -> dict[str, Any]:
        """List DHCP leases (connected devices)."""
        stdout, stderr, code = await self.ssh.execute("cat /tmp/dhcp.leases")
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch DHCP leases"}

        leases = []
        for line in stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 4:
                hostname = parts[3] if len(parts) > 3 else None
                if hostname == "*":
                    hostname = None

                leases.append(
                    {
                        "expires_at": parts[0],
                        "mac": parts[1].lower(),
                        "ip": parts[2],
                        "hostname": hostname,
                    }
                )

        return {
            "success": True,
            "leases_count": len(leases),
            "leases": leases[:50],
        }

    async def get_firewall_rules(self) -> dict[str, Any]:
        """Fetch firewall rules (supports iptables, nftables, and fw4)."""
        commands = [
            ("nft list ruleset 2>/dev/null", "nftables"),
            ("fw4 status 2>/dev/null", "fw4"),
            ("iptables -L -n -v", "iptables"),
        ]

        for cmd, firewall_type in commands:
            stdout, stderr, code = await self.ssh.execute(cmd)
            if code == 0 and stdout.strip():
                cleaned_output = "\n".join(
                    line
                    for line in stdout.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                )[:2500]

                return {
                    "success": True,
                    "firewall_type": firewall_type,
                    "rules_preview": cleaned_output,
                    "full_output_truncated": len(stdout) > 2500,
                }

        return {
            "success": False,
            "error": "No supported firewall found (iptables, nftables, fw4).",
        }

    async def read_uci_config(self, config_name: str) -> dict[str, Any]:
        """Read UCI configuration."""
        known_configs = [
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
        ]

        if not config_name or not re.match(r"^[a-zA-Z0-9._-]+$", config_name):
            raise ValidationError("Invalid configuration name")
        if config_name not in known_configs:
            raise ValidationError(
                f"Configuration '{config_name}' not supported. Allowed: {', '.join(known_configs)}"
            )

        stdout, stderr, code = await self.ssh.execute(f"uci show {config_name}")
        if code != 0:
            return {
                "success": False,
                "error": stderr or f"Configuration '{config_name}' does not exist",
            }

        config = {}
        for line in stdout.strip().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                config[key] = value.strip("'\"")

        return {
            "success": True,
            "config_name": config_name,
            "entries_count": len(config),
            "sample": dict(list(config.items())[:20]),
        }

    async def list_installed_packages(self) -> dict[str, Any]:
        """List installed packages."""
        stdout, stderr, code = await self.ssh.execute("opkg list-installed")
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch package list"}

        packages = []
        for line in stdout.strip().splitlines():
            parts = line.split(" - ")
            if len(parts) >= 2:
                packages.append({"name": parts[0].strip(), "version": parts[1].strip()})
            elif parts:
                packages.append({"name": parts[0].strip(), "version": "unknown"})

        return {
            "success": True,
            "packages_count": len(packages),
            "packages_sample": packages[:20],
        }

    async def get_router_logs(self, lines: int = 50, filter_level: str = "all") -> dict[str, Any]:
        """Fetch router logs."""
        lines = min(max(lines, 10), 200)
        cmd = f"logread -l {lines}"

        stdout, stderr, code = await self.ssh.execute(cmd)
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch logs"}

        log_lines = stdout.strip().splitlines()
        if filter_level != "all":
            filter_lower = filter_level.lower()
            log_lines = [line for line in log_lines if filter_lower in line.lower()]

        return {
            "success": True,
            "lines_count": len(log_lines),
            "logs": "\n".join(log_lines[:lines])[:3000],
        }

    async def search_router_logs(self, search_term: str, max_results: int = 30) -> dict[str, Any]:
        """Search for a phrase in router logs (Python-side filtering)."""
        # SECURITY: Validate search term
        if not SecurityValidator.is_safe_search_term(search_term):
            return _error_dict_extended(
                "INVALID_PARAM",
                "Unsafe or invalid search phrase",
                False,
                suggestion="Use only alphanumeric characters, spaces, dots, dashes, and colons.",
            )

        cmd = "logread -l 500"
        stdout, stderr, code = await self.ssh.execute(cmd)

        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch logs"}

        term_lower = search_term.lower()
        matches = [line for line in stdout.splitlines() if term_lower in line.lower()]

        return {
            "success": True,
            "search_term": search_term,
            "results_count": len(matches),
            "results": "\n".join(matches[-max_results:])[:3000],
        }

    async def diagnose_router_connectivity(self) -> dict[str, Any]:
        """Test basic router network services."""
        results: dict[str, Any] = {"success": True, "tests": {}, "summary": {}}

        # 1. Test DNS (8.8.8.8)
        stdout, stderr, code = await self.ssh.execute("ping -c 2 -W 2 8.8.8.8")
        results["tests"]["dns_google"] = {
            "success": code == 0,
            "output": (stdout or stderr)[:200],
        }

        # 2. Internet test (cloudflare.com)
        stdout, stderr, code = await self.ssh.execute("nslookup cloudflare.com 8.8.8.8")
        results["tests"]["internet_dns"] = {
            "success": code == 0 and ("Address" in stdout or "Name:" in stdout),
            "output": (stdout or stderr)[:200],
        }

        # 3. Gateway test
        stdout_route, _, _ = await self.ssh.execute("ip route show")
        gateway = None

        if stdout_route:
            for line in stdout_route.splitlines():
                if "default" in line and "via" in line:
                    parts = line.split()
                    try:
                        via_index = parts.index("via")
                        if via_index + 1 < len(parts):
                            gateway = parts[via_index + 1]
                            break
                    except ValueError:
                        pass

        if gateway:
            stdout, stderr, code = await self.ssh.execute(f"ping -c 2 -W 1 {gateway}")
            results["tests"]["gateway"] = {
                "success": code == 0,
                "gateway_ip": gateway,
                "output": (stdout or stderr)[:200],
            }
        else:
            results["tests"]["gateway"] = {
                "success": False,
                "error": "No default gateway found in routing table",
            }

        # 4. Local DNS test
        stdout, stderr, code = await self.ssh.execute("nslookup openwrt.lan 127.0.0.1")
        results["tests"]["local_dns"] = {
            "success": code == 0,
            "output": (stdout or stderr)[:200],
        }

        total_tests = len(results["tests"])
        passed_tests = sum(1 for t in results["tests"].values() if t["success"])

        results["summary"] = {
            "passed": passed_tests,
            "failed": total_tests - passed_tests,
            "total": total_tests,
            "health": "excellent"
            if passed_tests == total_tests
            else "good"
            if passed_tests >= total_tests - 1
            else "poor",
        }
        return results

    async def get_dhcp_static_leases(self) -> dict[str, Any]:
        """Fetch static DHCP reservations."""
        stdout, stderr, code = await self.ssh.execute("uci show dhcp")
        if code != 0:
            return {"success": False, "error": "Failed to fetch DHCP configuration"}

        static_leases: list[dict[str, str]] = []
        current_host: dict[str, str] = {}
        current_index: str | None = None

        for line in stdout.splitlines():
            host_match = re.match(r"dhcp\.@host\[(\d+)\]\.(\w+)='?([^']*)'?", line)
            if host_match:
                index = host_match.group(1)
                key = host_match.group(2)
                value = host_match.group(3)

                if index != current_index:
                    if current_host and "mac" in current_host:
                        static_leases.append(current_host.copy())
                    current_host = {}
                    current_index = index

                if key == "mac":
                    current_host["mac"] = value.lower()
                elif key == "ip":
                    current_host["ip"] = value
                elif key in ("name", "hostname"):
                    current_host["hostname"] = value

        if current_host and "mac" in current_host:
            static_leases.append(current_host)

        return {
            "success": True,
            "static_leases_count": len(static_leases),
            "leases": static_leases,
        }

    async def search_dhcp_logs(self, search_term: str) -> dict[str, Any]:
        """Search DHCP events in logs (Python-side)."""
        if not SecurityValidator.is_safe_search_term(search_term):
            return _error_dict_extended(
                "INVALID_PARAM",
                "Unsafe search term",
                False,
            )

        cmd = "logread -l 500"
        stdout, stderr, code = await self.ssh.execute(cmd)

        if code != 0:
            return {"success": False, "error": "Failed to fetch logs"}

        events = []
        term_lower = search_term.lower()

        for line in stdout.splitlines():
            line_lower = line.lower()
            if "dnsmasq" in line_lower or "dhcp" in line_lower:
                if term_lower in line_lower:
                    event_type = "unknown"
                    if "DHCPACK" in line:
                        event_type = "ack"
                    elif "DHCPREQUEST" in line:
                        event_type = "request"
                    elif "DHCPDISCOVER" in line:
                        event_type = "discover"
                    elif "DHCPOFFER" in line:
                        event_type = "offer"
                    elif "DHCPNAK" in line:
                        event_type = "nak"
                    elif "DHCPRELEASE" in line:
                        event_type = "release"

                    events.append(
                        {
                            "raw_log": line[:200],
                            "event_type": event_type,
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
        self, mac_address: str | None = None, ip_address: str | None = None
    ) -> dict[str, Any]:
        """Collect full device info: lease, reservation, and logs."""
        if not mac_address and not ip_address:
            raise ValidationError("Provide device MAC or IP")

        if mac_address:
            mac_address = mac_address.lower().replace("-", ":")
            if not re.match(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", mac_address):
                return _error_dict_extended(
                    "INVALID_PARAM",
                    "Invalid MAC address format",
                    False,
                    suggestion="Use format aa:bb:cc:dd:ee:ff",
                )

        if ip_address:
            if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip_address):
                return _error_dict_extended(
                    "INVALID_PARAM",
                    "Invalid IP address format",
                    False,
                    suggestion="Use format 192.168.1.100",
                )

        leases_res = await self.list_dhcp_leases()
        current_lease = None
        if leases_res.get("success"):
            for lease in leases_res.get("leases", []):
                if (mac_address and lease.get("mac") == mac_address) or (
                    ip_address and lease.get("ip") == ip_address
                ):
                    current_lease = lease
                    break

        static_res = await self.get_dhcp_static_leases()
        static_reservation = None
        if static_res.get("success"):
            for s in static_res.get("leases", []):
                if (mac_address and s.get("mac") == mac_address) or (
                    ip_address and s.get("ip") == ip_address
                ):
                    static_reservation = s
                    break

        search_val = mac_address or ip_address
        logs_res = await self.search_dhcp_logs(search_val)  # type: ignore[arg-type]

        return {
            "success": True,
            "device_identifier": search_val,
            "current_lease": current_lease,
            "static_reservation": static_reservation,
            "has_static_reservation": static_reservation is not None,
            "is_currently_connected": current_lease is not None,
            "recent_log_events": logs_res.get("events", [])[:5],
            "note": "DHCP logs require 'log_dhcp' enabled in dnsmasq configuration.",
        }

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        return " ".join(parts) if parts else "0m"


# Singleton
_explorer: OpenWRTExplorer | None = None


def get_explorer() -> OpenWRTExplorer:
    global _explorer
    if _explorer is None:
        _explorer = OpenWRTExplorer()
    return _explorer
