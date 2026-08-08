from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.mock_explorer import MockOpenWRTExplorer
from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.explorer import OpenWRTExplorer
from openwrt_mcp.validators import ValidationError


class NoDispatchSSH:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def execute(self, command: str) -> tuple[str, str, int]:
        self.commands.append(command)
        raise AssertionError(f"invalid input reached SSH dispatch: {command}")

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "arguments"),
    [
        ("read_uci_config", ("network;reboot",)),
        ("read_uci_config", ("shadow",)),
        ("search_router_logs", ("x;reboot", 10)),
        ("search_dhcp_logs", ("x;reboot",)),
        ("get_device_dhcp_details", ("broken", None)),
        ("get_device_dhcp_details", (None, "999.999.999.999")),
        ("ping_host", ("bad;reboot", 1)),
        ("traceroute_host", ("bad;reboot",)),
        ("nslookup_host", ("example.com", "8.8.8.8;reboot")),
        ("wifi_scan", ("wlan0;reboot",)),
    ],
)
async def test_mock_and_real_explorer_reject_the_same_invalid_shell_bound_values(
    tmp_path: Path,
    method: str,
    arguments: tuple[Any, ...],
) -> None:
    ssh = NoDispatchSSH()
    real = OpenWRTExplorer(settings(tmp_path), ssh=ssh)
    mock = MockOpenWRTExplorer()

    for explorer in (real, mock):
        operation = getattr(explorer, method)
        with pytest.raises(ValidationError):
            await operation(*arguments)
    assert ssh.commands == []
