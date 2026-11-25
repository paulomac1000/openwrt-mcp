from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from openwrt_mcp.tools.writer import OpenWRTWriter
from openwrt_mcp.validators import ValidationError


@pytest.mark.parametrize("code", [0, 1])
async def test_uci_set_does_not_echo_value_or_upstream_error(code: int) -> None:
    canary = "synthetic-writer-canary-e22"
    ssh = AsyncMock()
    ssh.execute_write.return_value = ("", f"failed at {canary}", code)
    result = await OpenWRTWriter(ssh).uci_set("network", "wan", "proto", canary)
    assert result["success"] is (code == 0)
    assert canary not in repr(result)


async def test_writer_rejects_injection_before_ssh() -> None:
    ssh = AsyncMock()
    writer = OpenWRTWriter(ssh)
    with pytest.raises(ValidationError):
        await writer.uci_set("network", "wan", "ipaddr", "x;reboot")
    ssh.execute_write.assert_not_awaited()


async def test_restart_reports_partial_success_and_compensation() -> None:
    ssh = AsyncMock()
    ssh.execute_write.side_effect = [("", "", 0), ("", "failed", 1)]
    result = await OpenWRTWriter(ssh).restart_interface("wan")
    assert result["partial_success"] is True
    assert "compensation" in result


async def test_remaining_writer_operations_use_fixed_commands() -> None:
    ssh = AsyncMock()
    ssh.execute_write.return_value = ("ok", "", 0)
    writer = OpenWRTWriter(ssh)
    assert (await writer.reload_network())["success"] is True
    assert (await writer.uci_set("network", "wan", "proto", "dhcp"))["success"] is True
    assert (await writer.uci_commit("network"))["success"] is True
    assert (await writer.reboot_device())["success"] is True
    commands = [call.args[0] for call in ssh.execute_write.await_args_list]
    assert commands == [
        "/etc/init.d/network reload",
        "uci set network.wan.proto=dhcp",
        "uci commit network",
        "ubus call system reboot",
    ]
