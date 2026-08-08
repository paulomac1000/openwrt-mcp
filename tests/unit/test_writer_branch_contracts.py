from __future__ import annotations

from typing import Any

import pytest

from openwrt_mcp.tools.writer import OpenWRTWriter


class ScriptedSSH:
    def __init__(self, *responses: tuple[str, str, int]) -> None:
        self.responses = list(responses)
        self.commands: list[str] = []

    async def execute_write(self, command: str, **_: Any) -> tuple[str, str, int]:
        self.commands.append(command)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_restart_interface_covers_ifup_failure_and_success() -> None:
    failed_ssh = ScriptedSSH(("", "", 0), ("", "ifup failed", 1))
    failed = await OpenWRTWriter(failed_ssh).restart_interface("wan")
    assert failed["phase"] == "ifup"
    assert failed["partial_success"] is True

    success_ssh = ScriptedSSH(("", "", 0), ("", "", 0))
    success = await OpenWRTWriter(success_ssh).restart_interface("wan")
    assert success == {"success": True, "interface": "wan", "action": "restarted"}


@pytest.mark.asyncio
async def test_uci_set_and_commit_cover_success_and_failure() -> None:
    failed_set = await OpenWRTWriter(ScriptedSSH(("", "set failed", 1))).uci_set(
        "network", "wan", "metric", "10"
    )
    assert failed_set == {"success": False, "error": "set failed"}

    success_set = await OpenWRTWriter(ScriptedSSH(("", "", 0))).uci_set(
        "network", "wan", "metric", "10"
    )
    assert success_set["action"] == "uci_set_uncommitted"

    success_commit = await OpenWRTWriter(ScriptedSSH(("", "", 0))).uci_commit("network")
    failed_commit = await OpenWRTWriter(ScriptedSSH(("", "commit failed", 1))).uci_commit("network")
    assert success_commit["success"] is True
    assert failed_commit == {"success": False, "error": "commit failed"}


@pytest.mark.asyncio
async def test_reload_and_reboot_cover_both_result_branches() -> None:
    assert (await OpenWRTWriter(ScriptedSSH(("", "", 0))).reload_network())["success"] is True
    assert await OpenWRTWriter(ScriptedSSH(("", "reload failed", 1))).reload_network() == {
        "success": False,
        "error": "reload failed",
    }
    assert (await OpenWRTWriter(ScriptedSSH(("", "", 0))).reboot_device())[
        "action"
    ] == "reboot_accepted"
    assert await OpenWRTWriter(ScriptedSSH(("", "reboot failed", 1))).reboot_device() == {
        "success": False,
        "error": "reboot failed",
    }
