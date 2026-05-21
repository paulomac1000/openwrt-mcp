"""
Test fixtures for OpenWRT-MCP unit tests.

CAUTION: .env MUST be loaded here at project level, before any test file or
openwrt_mcp module is imported. This ensures os.getenv() in constants.py
picks up the correct values.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Load .env before any test runs — env vars must be set before constants.py
# evaluates os.getenv(). This runs at import time, which precedes any test
# file import due to pytest's conftest discovery order.
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

# Mock data for OpenWRT responses
MOCK_BOARD_JSON = json.dumps(
    {
        "model": {"id": "xiaomi,ax3600", "name": "Xiaomi AX3600"},
        "system": "Qualcomm Atheros QCA9860",
        "hostname": "OpenWrt",
        "release": {
            "distribution": "OpenWrt",
            "version": "23.05.3",
            "revision": "r23809-234f1a2b3c",
            "target": "ipq807x/generic",
            "description": "OpenWrt 23.05.3 r23809-234f1a2b3c",
        },
        "kernel": "5.15.150",
    }
)

MOCK_DHCP_LEASES = """1770185708 de:ad:be:ef:00:01 192.168.0.193 * 01:de:ad:be:ef:00:01
1770196154 de:ad:be:ef:00:02 192.168.0.126 test-device 01:de:ad:be:ef:00:02
1770185000 de:ad:be:ef:00:03 192.168.0.10 device1 01:de:ad:be:ef:00:03
"""

MOCK_WIRELESS_STATUS = json.dumps(
    {
        "radio0": {
            "interfaces": [
                {
                    "type": "ap",
                    "config": {"ssid": "MyNetwork", "mode": "ap"},
                    "ifname": "wlan0",
                    "stations": [{"mac": "de:ad:be:ef:00:03", "signal": -45, "inactive": 120}],
                }
            ]
        }
    }
)

MOCK_UPTIME = """1776951.23 1776951.23
"""

MOCK_MEMORY = """MemTotal:       123456 kB
MemFree:         65432 kB
Buffers:          1234 kB
Cached:           5678 kB
"""

MOCK_LOADAVG = """0.45 0.32 0.28 2/234 12345
"""


def _make_run_mock():
    """Create a run mock that returns different outputs per command."""

    async def run_side_effect(cmd, **kwargs):
        stdout = ""
        stderr = ""
        exit_status = 0
        if "system board" in cmd:
            stdout = MOCK_BOARD_JSON
        elif "network.wireless status" in cmd:
            stdout = MOCK_WIRELESS_STATUS
        elif "dhcp.leases" in cmd:
            stdout = MOCK_DHCP_LEASES
        elif "cat /proc/uptime" in cmd:
            stdout = MOCK_UPTIME
        elif "cat /proc/meminfo" in cmd:
            stdout = MOCK_MEMORY
        elif "cat /proc/loadavg" in cmd:
            stdout = MOCK_LOADAVG
        elif "uci show" in cmd:
            stdout = "firewall.@rule[0]=rule\nfirewall.@rule[0].name='Allow-SSH'\n"
        elif "opkg list-installed" in cmd:
            stdout = "luci - git-24.\nfirewall - 2023-05-01\n"
        elif "logread" in cmd:
            stdout = "Apr 23 10:00:00 OpenWrt dnsmasq[1]: DHCPACK(br-lan) 192.168.0.100 abc\n"
        elif "ping" in cmd:
            stdout = "64 bytes from 8.8.8.8: seq=0 ttl=118 time=15.2 ms\n"
        elif "traceroute" in cmd:
            stdout = (
                "traceroute to 8.8.8.8 (8.8.8.8), 30 hops max\n"
                " 1  192.168.1.1  0.5 ms\n 2  10.0.0.1  2.0 ms\n"
            )
        elif "nslookup" in cmd:
            stdout = (
                "Server:  8.8.8.8\nAddress: 8.8.8.8#53\nName: google.com\nAddress: 142.250.80.46\n"
            )
        elif "iwinfo" in cmd and "scan" in cmd:
            stdout = (
                "Cell 01 - Address: AA:BB:CC:DD:EE:01\n"
                '  ESSID: "NeighborNet"\n  Mode: Master  Channel: 6\n'
                "  Signal level: -65 dBm\n"
            )
        elif "uci set" in cmd:
            stdout = ""
        elif "uci commit" in cmd:
            stdout = ""
        elif "ubus call system reboot" in cmd:
            stdout = ""
        else:
            stdout = "{}"
        return MagicMock(stdout=stdout, stderr=stderr, exit_status=exit_status)

    return AsyncMock(side_effect=run_side_effect)


@pytest.fixture
def mock_openwrt_ssh():
    """Mock asyncssh connection."""
    with patch("asyncssh.connect", new_callable=AsyncMock) as mock:
        with patch("pathlib.Path.exists", return_value=True):
            mock_conn = AsyncMock()
            mock_conn.run = _make_run_mock()
            mock_conn.close = MagicMock()
            mock_conn.wait_closed = AsyncMock()
            mock.return_value = mock_conn
            yield mock


@pytest.fixture
def openwrt_env():
    """Set OpenWRT environment variables."""
    with patch.dict(
        "os.environ",
        {
            "OPENWRT_HOST": "192.168.0.200",
            "OPENWRT_USER": "root",
            "OPENWRT_SSH_KEY": "/app/keys/test_key",
        },
    ):
        yield


@pytest.fixture
def openwrt_test_data():
    """Provide sample validated response data for schema tests."""
    return {
        "get_system_info": {
            "success": True,
            "model": "Xiaomi AX3600",
            "hostname": "OpenWrt",
            "openwrt_version": "23.05.3",
            "kernel": "5.15.150",
            "uptime_seconds": 1776951,
            "uptime": "20 days, 13:35:51",
            "memory_used_percent": 47.0,
            "memory_total_bytes": 126420864,
            "memory_free_bytes": 67002368,
        },
        "list_dhcp_leases": {
            "success": True,
            "leases_count": 3,
            "leases": [
                {
                    "expires_at": "2026-04-23T10:00:00",
                    "mac": "22:28:4d:03:23:0c",
                    "ip": "192.168.0.193",
                    "hostname": None,
                },
                {
                    "expires_at": "2026-04-23T10:00:00",
                    "mac": "dc:c6:02:db:3e:d7",
                    "ip": "192.168.0.126",
                    "hostname": "iPhone",
                },
                {
                    "expires_at": "2026-04-23T10:00:00",
                    "mac": "aa:bb:cc:dd:ee:01",
                    "ip": "192.168.0.10",
                    "hostname": "device1",
                },
            ],
        },
        "diagnose_router_connectivity": {
            "success": True,
            "tests": {
                "internet": {
                    "success": True,
                    "latency_ms": 15.2,
                    "details": "8.8.8.8 reachable",
                },
                "dns": {
                    "success": True,
                    "latency_ms": 5.0,
                    "details": "DNS resolution works",
                },
            },
            "summary": "all_passed - health check passed",
        },
    }


@pytest.fixture
def mock_mcp():
    """Mock MCP instance that stores registered tools — Canonical Template 9."""
    mcp = MagicMock()
    mcp._tools = {}

    def tool_decorator(*args, **kwargs):
        def wrapper(func):
            tool_name = kwargs.get("name", func.__name__)
            mcp._tools[tool_name] = func
            return func

        if len(args) == 1 and callable(args[0]) and not kwargs:
            mcp._tools[args[0].__name__] = args[0]
            return args[0]
        return wrapper

    mcp.tool = tool_decorator
    mcp.get_tool = lambda name: mcp._tools.get(name)
    return mcp
