from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from openwrt_mcp.tools.explorer import OpenWRTExplorer
from openwrt_mcp.validators import ValidationError


class FakeSSH:
    def __init__(self) -> None:
        self.commands: list[str] = []

    @contextmanager
    def timeout_scope(self, _: int) -> Iterator[None]:
        yield

    async def execute(self, command: str) -> tuple[str, str, int]:
        self.commands.append(command)
        board = json.dumps(
            {
                "hostname": "router",
                "model": {"name": "MockBoard"},
                "kernel": "6.6",
                "release": {"version": "23.05"},
            }
        )
        responses: dict[str, tuple[str, str, int]] = {
            "ubus call system board": (board, "", 0),
            "cat /proc/uptime": ("90061.5 0", "", 0),
            "cat /proc/meminfo": (
                "MemTotal: 1000 kB\nMemAvailable: 250 kB\n", "", 0
            ),
            "ubus call network.wireless status": (
                json.dumps(
                    {
                        "radio0": {
                            "interfaces": [
                                {
                                    "type": "ap",
                                    "ifname": "wlan0",
                                    "config": {"ssid": "Test", "mode": "ap"},
                                    "stations": [
                                        {"mac": "02:00:00:00:00:01", "signal": -40}
                                    ],
                                }
                            ]
                        }
                    }
                ),
                "",
                0,
            ),
            "cat /tmp/dhcp.leases": (
                "1893456000 02:00:00:00:00:01 192.0.2.2 client *\n", "", 0
            ),
            "nft list ruleset": ("table inet fw4 {}", "", 0),
            "uci show network": ("network.lan=interface\nnetwork.lan.proto='static'", "", 0),
            "uci show dhcp": (
                "dhcp.host1=host\ndhcp.host1.mac='02:00:00:00:00:01'\n"
                "dhcp.host1.ip='192.0.2.2'\n",
                "",
                0,
            ),
            "opkg list-installed": ("base-files - 1\nbusybox - 2", "", 0),
            "logread -l 20": ("dnsmasq DHCPACK 192.0.2.2 client", "", 0),
            "logread -l 50": ("dnsmasq DHCPACK 192.0.2.2 client", "", 0),
            "logread -l 500": ("dnsmasq DHCPACK 192.0.2.2 client", "", 0),
            "ping -c 2 -W 2 8.8.8.8": ("ok", "", 0),
            "nslookup example.com 8.8.8.8": ("Address: 192.0.2.3", "", 0),
            "ping -c 2 -W 2 192.0.2.1": ("ok", "", 0),
            "traceroute -n 192.0.2.1": ("1 192.0.2.1", "", 0),
            "nslookup example.test 192.0.2.53": ("Address: 192.0.2.4", "", 0),
            "iwinfo wlan0 scan": ("Cell 01 - Address: 02:00:00:00:00:02", "", 0),
        }
        return responses.get(command, ("", f"unexpected command: {command}", 1))

    async def close(self) -> None:
        return None


@pytest.fixture
def explorer(settings: Any) -> OpenWRTExplorer:
    return OpenWRTExplorer(settings, ssh=FakeSSH())


async def test_system_wifi_dhcp_and_firewall_parsing(explorer: OpenWRTExplorer) -> None:
    connection = await explorer.test_connection()
    system = await explorer.get_system_info()
    wifi = await explorer.get_wifi_status()
    leases = await explorer.list_dhcp_leases()
    firewall = await explorer.get_firewall_rules()
    assert connection["model"] == "MockBoard"
    assert system["memory_used_percent"] == 75.0
    assert system["uptime"] == "1 days, 01:01:01"
    assert wifi["interfaces"][0]["clients_count"] == 1
    assert leases["leases"][0]["hostname"] == "client"
    assert firewall["firewall_type"] == "nftables"


async def test_config_package_log_and_dhcp_workflows(explorer: OpenWRTExplorer) -> None:
    config = await explorer.read_uci_config("network")
    packages = await explorer.list_installed_packages()
    logs = await explorer.get_router_logs(20, "all")
    search = await explorer.search_router_logs("client", 5)
    static = await explorer.get_dhcp_static_leases()
    events = await explorer.search_dhcp_logs("client")
    details = await explorer.get_device_dhcp_details(ip_address="192.0.2.2")
    assert config["entries_count"] == 2
    assert packages["packages_count"] == 2
    assert logs["lines_count"] == 1
    assert search["results_count"] == 1
    assert static["static_leases_count"] == 1
    assert events["events"][0]["event_type"] == "dhcpack"
    assert details["is_currently_connected"] is True
    assert details["has_static_reservation"] is True


async def test_diagnostics_context_and_network_tools(explorer: OpenWRTExplorer) -> None:
    diagnostics = await explorer.diagnose_router_connectivity()
    context = await explorer.get_router_context()
    ping = await explorer.ping_host("192.0.2.1", 2)
    trace = await explorer.traceroute_host("192.0.2.1")
    lookup = await explorer.nslookup_host("example.test", "192.0.2.53")
    scan = await explorer.wifi_scan("wlan0")
    assert diagnostics["summary"]["passed"] == 2
    assert context["partial"] is False
    assert ping["success"] and trace["success"] and lookup["success"] and scan["success"]


@pytest.mark.parametrize(
    "call",
    [
        lambda service: service.read_uci_config("../../etc/shadow"),
        lambda service: service.search_router_logs("x;reboot"),
        lambda service: service.ping_host("example.com;reboot"),
        lambda service: service.wifi_scan("lo"),
    ],
)
async def test_invalid_inputs_fail_before_ssh(explorer: OpenWRTExplorer, call: Any) -> None:
    ssh = explorer.ssh
    before = list(ssh.commands)
    with pytest.raises(ValidationError):
        await call(explorer)
    assert ssh.commands == before
