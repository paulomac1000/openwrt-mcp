"""Dormant write-domain operations.

Write tools are intentionally not registered in the hardened MCP profile until
principal-bound, expiring approvals are implemented. The domain adapter remains
covered by tests for a future authenticated profile.
"""

from __future__ import annotations

from typing import Any

from openwrt_mcp.tools.ssh_client import SSHConnection
from openwrt_mcp.validators import SecurityValidator


class OpenWRTWriter:
    def __init__(self, ssh: SSHConnection) -> None:
        self.ssh = ssh

    async def restart_interface(
        self, interface_name: str, *, timeout_seconds: int | None = None
    ) -> dict[str, Any]:
        interface = SecurityValidator.validate_interface_name(interface_name)
        _, error, code = await self.ssh.execute_write(
            f"ifdown {interface}", timeout_seconds=timeout_seconds
        )
        if code != 0:
            return {"success": False, "error": error, "phase": "ifdown"}
        _, error, code = await self.ssh.execute_write(
            f"ifup {interface}", timeout_seconds=timeout_seconds
        )
        if code != 0:
            return {
                "success": False,
                "error": error,
                "phase": "ifup",
                "partial_success": True,
                "compensation": "Manually run ifup after checking interface state.",
            }
        return {"success": True, "interface": interface, "action": "restarted"}

    async def uci_set(
        self,
        config: str,
        section: str,
        option: str,
        value: str,
        *,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        command = SecurityValidator.build_uci_set_command(config, section, option, value)
        _, error, code = await self.ssh.execute_write(command, timeout_seconds=timeout_seconds)
        if code != 0:
            return {"success": False, "error": error}
        return {
            "success": True,
            "config": config,
            "section": section,
            "option": option,
            "action": "uci_set_uncommitted",
        }

    async def uci_commit(
        self, config: str, *, timeout_seconds: int | None = None
    ) -> dict[str, Any]:
        config = SecurityValidator.validate_uci_config(config)
        _, error, code = await self.ssh.execute_write(
            f"uci commit {config}", timeout_seconds=timeout_seconds
        )
        return (
            {"success": True, "config": config, "action": "uci_committed"}
            if code == 0
            else {"success": False, "error": error}
        )

    async def reload_network(
        self, *, timeout_seconds: int | None = None
    ) -> dict[str, Any]:
        _, error, code = await self.ssh.execute_write(
            "/etc/init.d/network reload", timeout_seconds=timeout_seconds
        )
        return (
            {"success": True, "action": "network_reloaded"}
            if code == 0
            else {"success": False, "error": error}
        )

    async def reboot_device(
        self, *, timeout_seconds: int | None = None
    ) -> dict[str, Any]:
        _, error, code = await self.ssh.execute_write(
            "ubus call system reboot", timeout_seconds=timeout_seconds
        )
        return (
            {
                "success": True,
                "action": "reboot_accepted",
                "verification": "Reconnect using test_router_connection after the operator window.",
            }
            if code == 0
            else {"success": False, "error": error}
        )
