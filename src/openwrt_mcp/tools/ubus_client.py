"""
UbusClient — ubus JSON-RPC over SSH-tunneled HTTP.

Alternative transport layer alongside direct SSH command execution.
Requires uhttpd-mod-ubus package on the router.
"""

from typing import Any


class UbusClient:
    """Ubus JSON-RPC client that tunnels HTTP through SSH."""

    def __init__(self, ssh_connection: Any) -> None:
        self.ssh = ssh_connection

    async def _ubus_call(
        self, namespace: str, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a ubus call via SSH."""
        import json as _json

        json_params = _json.dumps(params or {})
        cmd = f"ubus call {namespace} {method} '{json_params}'"
        stdout, stderr, code = await self.ssh.execute(cmd)

        if code != 0:
            return {"success": False, "error": stderr or stdout or "ubus call failed"}

        try:
            result = _json.loads(stdout)
            if isinstance(result, list) and len(result) == 2:
                error_code, data = result
                if error_code != 0:
                    return {"success": False, "error": f"ubus error {error_code}", "data": data}
                return {"success": True, "data": data}
            return {"success": True, "data": result}
        except Exception:
            return {"success": True, "data": stdout}

    async def get_system_board(self) -> dict[str, Any]:
        """Get system board info via ubus."""
        return await self._ubus_call("system", "board")

    async def get_network_devices(self) -> dict[str, Any]:
        """Get network device status via ubus."""
        result = await self._ubus_call("network.device", "status")
        return result

    async def list_ubus_objects(self) -> dict[str, Any]:
        """List all registered ubus objects."""
        stdout, stderr, code = await self.ssh.execute("ubus list")
        if code != 0:
            return {"success": False, "error": stderr or "ubus list failed"}
        objects = [line.strip() for line in stdout.strip().splitlines() if line.strip()]
        return {"success": True, "objects": objects, "count": len(objects)}
