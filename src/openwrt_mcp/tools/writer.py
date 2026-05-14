"""
OpenWRT Writer — write/action operations on the router.
Only available when ENABLE_WRITE_OPERATIONS=1 is set.
"""

import logging
from typing import Any

from openwrt_mcp.tools.constants import ENABLE_WRITE_OPERATIONS
from openwrt_mcp.tools.ssh_client import SSHConnection
from openwrt_mcp.validators import SecurityValidator, ValidationError

logger = logging.getLogger("openwrt-mcp.writer")


class OpenWRTWriter:
    """Write operations for OpenWRT router (network restart/reload).

    Only functional when ENABLE_WRITE_OPERATIONS=1 is set.
    Shares the SSH connection from the explorer singleton.
    """

    def __init__(self, ssh: SSHConnection) -> None:
        self.ssh = ssh

    async def restart_interface(self, interface_name: str) -> dict[str, Any]:
        """Restart a network interface (ifdown + ifup)."""
        SecurityValidator.validate_interface_name(interface_name)

        stdout_down, stderr_down, code_down = await self.ssh.execute_write(
            f"ifdown {interface_name}"
        )
        if code_down != 0:
            return {
                "success": False,
                "error": stderr_down or f"Failed to bring down interface '{interface_name}'",
            }

        stdout_up, stderr_up, code_up = await self.ssh.execute_write(f"ifup {interface_name}")
        if code_up != 0:
            return {
                "success": False,
                "error": stderr_up or f"Failed to bring up interface '{interface_name}'",
            }

        return {
            "success": True,
            "interface": interface_name,
            "action": "restarted",
            "down_output": stdout_down[:200] if stdout_down else "",
            "up_output": stdout_up[:200] if stdout_up else "",
        }

    async def reload_network(self) -> dict[str, Any]:
        """Reload network service (/etc/init.d/network reload)."""
        stdout, stderr, code = await self.ssh.execute_write("/etc/init.d/network reload")
        if code != 0:
            return {
                "success": False,
                "error": stderr or "Failed to reload network service",
            }

        return {
            "success": True,
            "action": "network_reloaded",
            "output": stdout[:200] if stdout else "",
        }

    async def uci_set(self, config: str, section: str, option: str, value: str) -> dict[str, Any]:
        """Set a UCI configuration value."""
        uci_path = f"{config}.{section}.{option}"
        cmd = f"uci set {uci_path}={value}"

        stdout, stderr, code = await self.ssh.execute_write(cmd)
        if code != 0:
            return {"success": False, "error": stderr or f"Failed to set {uci_path}"}

        return {
            "success": True,
            "config": config,
            "section": section,
            "option": option,
            "value": value,
            "action": "uci_set",
        }

    async def uci_commit(self, config: str) -> dict[str, Any]:
        """Commit UCI configuration changes."""
        cmd = f"uci commit {config}"
        stdout, stderr, code = await self.ssh.execute_write(cmd)
        if code != 0:
            return {"success": False, "error": stderr or f"Failed to commit {config}"}

        return {
            "success": True,
            "config": config,
            "action": "uci_committed",
        }

    async def reboot_device(self) -> dict[str, Any]:
        """Reboot the router (ubus call system reboot)."""
        stdout, stderr, code = await self.ssh.execute_write("ubus call system reboot")
        if code != 0:
            return {"success": False, "error": stderr or "Failed to reboot device"}

        return {
            "success": True,
            "action": "reboot_initiated",
            "note": "Device is rebooting. Connection will be lost momentarily.",
        }


def check_write_enabled() -> None:
    """Raise ValidationError if write operations are not enabled."""
    if not ENABLE_WRITE_OPERATIONS:
        raise ValidationError(
            "Write operations are disabled. Set ENABLE_WRITE_OPERATIONS=1 to enable."
        )


# Singleton
_writer: OpenWRTWriter | None = None


def get_writer(ssh: SSHConnection) -> OpenWRTWriter:
    global _writer
    if _writer is None:
        _writer = OpenWRTWriter(ssh)
    return _writer
