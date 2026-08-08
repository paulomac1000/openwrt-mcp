from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.explorer import OpenWRTExplorer
from openwrt_mcp.validators import ValidationError


class SSH:
    def __init__(self, responses: dict[str, tuple[str, str, int]]) -> None:
        self.responses = responses
        self.commands: list[str] = []

    @contextmanager
    def timeout_scope(self, _: int) -> Iterator[None]:
        yield

    async def execute(self, command: str) -> tuple[str, str, int]:
        self.commands.append(command)
        return self.responses.get(command, ("", "missing fake response", 1))

    async def close(self) -> None:
        return None


def settings(tmp_path: Path) -> Settings:
    return Settings(
        openwrt_host="router.test",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=tmp_path / "key",
        openwrt_password=None,
        openwrt_known_hosts=tmp_path / "known_hosts",
        ssh_timeout=30,
        health_port=19094,
        log_level="INFO",
        enable_audit_logging=False,
        audit_log_file=tmp_path / "audit.log",
        mcp_transport="stdio",
        mock_mode=True,
    )


def explorer(tmp_path: Path, responses: dict[str, tuple[str, str, int]]) -> OpenWRTExplorer:
    return OpenWRTExplorer(settings(tmp_path), ssh=SSH(responses))


@pytest.mark.asyncio
async def test_connection_and_system_error_paths(tmp_path: Path) -> None:
    disconnected = explorer(tmp_path, {"ubus call system board": ("", "denied", 1)})
    assert (await disconnected.test_connection())["status"] == "disconnected"
    assert (await disconnected.get_system_info())["success"] is False

    malformed = explorer(tmp_path, {"ubus call system board": ("not-json", "", 0)})
    assert (await malformed.test_connection())["status"] == "unresponsive"
    assert (await malformed.get_system_info())["error"] == "Invalid board response"

    board = json.dumps({"hostname": "r", "model": "plain", "release": {}, "kernel": "k"})
    odd = explorer(
        tmp_path,
        {
            "ubus call system board": (board, "", 0),
            "cat /proc/uptime": ("bad", "", 0),
            "cat /proc/meminfo": ("MemFree: 12 kB\nNoColon", "", 0),
        },
    )
    info = await odd.get_system_info()
    assert info["uptime_seconds"] == 0
    assert info["memory_total_bytes"] == 0
    assert info["memory_used_percent"] == 0


@pytest.mark.asyncio
async def test_wifi_dhcp_firewall_fallbacks(tmp_path: Path) -> None:
    failed = explorer(
        tmp_path,
        {
            "ubus call network.wireless status": ("", "wireless down", 1),
            "cat /tmp/dhcp.leases": ("", "dhcp down", 1),
            "nft list ruleset": ("", "", 1),
            "fw4 status": ("rules\n# comment\nallow", "", 0),
        },
    )
    assert (await failed.get_wifi_status())["success"] is False
    assert (await failed.list_dhcp_leases())["success"] is False
    firewall = await failed.get_firewall_rules()
    assert firewall["firewall_type"] == "fw4"
    assert "# comment" not in firewall["rules_preview"]

    malformed = explorer(
        tmp_path,
        {"ubus call network.wireless status": ("not-json", "", 0)},
    )
    assert (await malformed.get_wifi_status())["error"] == "Invalid Wi-Fi response"

    wireless = json.dumps(
        {
            "radio0": {
                "interfaces": [
                    {
                        "type": "sta",
                        "section": "wlan-sta",
                        "config": {"ssid": "upstream"},
                        "clients": {"00:11:22:33:44:55": {"signal": -60, "idle": 4}},
                    }
                ]
            }
        }
    )
    station = explorer(tmp_path, {"ubus call network.wireless status": (wireless, "", 0)})
    result = await station.get_wifi_status()
    assert result["interfaces"][0]["ifname"] == "wlan-sta"
    assert result["interfaces"][0]["clients"][0]["idle"] == 4
    assert result["note"] is not None

    no_firewall = explorer(
        tmp_path,
        {
            "nft list ruleset": ("", "", 1),
            "fw4 status": ("", "", 1),
            "iptables -L -n -v": ("", "", 1),
        },
    )
    assert (await no_firewall.get_firewall_rules())["success"] is False


@pytest.mark.asyncio
async def test_config_packages_and_log_error_and_filter_paths(tmp_path: Path) -> None:
    service = explorer(
        tmp_path,
        {
            "uci show network": ("", "no config", 1),
            "opkg list-installed": ("", "opkg error", 1),
            "logread -l 10": ("info one\nERROR two\nwarning three", "", 0),
            "logread -l 500": ("alpha\nbeta alpha\ngamma", "", 0),
        },
    )
    assert (await service.read_uci_config("network"))["success"] is False
    assert (await service.list_installed_packages())["success"] is False
    logs = await service.get_router_logs(1, "error")
    assert logs["lines_count"] == 1
    assert logs["logs"] == "ERROR two"
    search = await service.search_router_logs("alpha", 1)
    assert search["results_count"] == 2
    assert search["results"] == "beta alpha"
    with pytest.raises(ValidationError, match="not supported"):
        await service.read_uci_config("notallowed")

    failing_logs = explorer(tmp_path, {"logread -l 10": ("", "log error", 1)})
    assert (await failing_logs.get_router_logs(10))["success"] is False


@pytest.mark.asyncio
async def test_diagnostics_without_gateway_and_static_dhcp_edge_paths(tmp_path: Path) -> None:
    service = explorer(
        tmp_path,
        {
            "ping -c 2 -W 2 8.8.8.8": ("", "no route", 1),
            "nslookup cloudflare.com 8.8.8.8": ("unresolved", "", 0),
            "ip route show": ("default via bad-gateway dev eth0", "", 0),
            "nslookup openwrt.lan 127.0.0.1": ("", "dns fail", 1),
            "uci show dhcp": (
                "dhcp.@host[0]=host\n"
                "dhcp.@host[0].mac='AA:BB:CC:DD:EE:FF'\n"
                "dhcp.@host[0].name='printer'\n"
                "dhcp.ignore=interface\n"
                "dhcp.ignore.ip='192.0.2.5'\n",
                "",
                0,
            ),
        },
    )
    diagnostic = await service.diagnose_router_connectivity()
    assert diagnostic["tests"]["gateway"]["success"] is False
    assert diagnostic["summary"]["health"] == "poor"
    leases = await service.get_dhcp_static_leases()
    assert leases["leases"] == [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "printer"}]

    failed = explorer(tmp_path, {"uci show dhcp": ("", "fail", 1)})
    assert (await failed.get_dhcp_static_leases())["success"] is False


@pytest.mark.asyncio
async def test_device_validation_network_failures_and_scan_parser(tmp_path: Path) -> None:
    service = explorer(
        tmp_path,
        {
            "ping -c 1 -W 2 example.test": ("", "unreachable", 1),
            "traceroute -n example.test": ("", "no traceroute", 1),
            "nslookup example.test 8.8.8.8": ("", "not found", 1),
            "iwinfo wlan0 scan": ("", "scan fail", 1),
        },
    )
    ping = await service.ping_host("example.test", 1)
    assert ping["success"] is False and ping["reachable"] is False
    trace = await service.traceroute_host("example.test")
    assert trace["success"] is True and trace["output"] == "no traceroute"
    lookup = await service.nslookup_host("example.test")
    assert lookup["success"] is True and lookup["resolved"] is False
    assert (await service.wifi_scan("wlan0"))["success"] is False

    with pytest.raises(ValidationError, match="Provide device"):
        await service.get_device_dhcp_details()
    with pytest.raises(ValidationError, match="Invalid MAC"):
        await service.get_device_dhcp_details(mac_address="broken")
    with pytest.raises(ValidationError, match="Invalid IP"):
        await service.get_device_dhcp_details(ip_address="999.999.999.999")

    parsed = service._parse_wifi_scan(
        "Cell 01 - Address: 00:11:22:33:44:55\nESSID: \"one\"\nChannel: 1\n"
        "Cell 02 - Address: 00:11:22:33:44:66\nESSID: \"two\"\nMode: Master\n"
    )
    assert [item["ssid"] for item in parsed] == ["one", "two"]


@pytest.mark.parametrize(
    ("line", "event"),
    [
        ("DHCPREQUEST foo", "request"),
        ("DHCPDISCOVER foo", "discover"),
        ("DHCPOFFER foo", "offer"),
        ("DHCPNAK foo", "nak"),
        ("DHCPRELEASE foo", "release"),
        ("something else", "unknown"),
    ],
)
def test_dhcp_event_classifier(line: str, event: str) -> None:
    assert OpenWRTExplorer._dhcp_event_type(line) == event
