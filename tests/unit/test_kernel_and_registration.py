from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from openwrt_mcp.tools.registration import build_invocation_kernel, register_openwrt_tools


class FakeSSH:
    @contextmanager
    def timeout_scope(self, seconds: int) -> Iterator[None]:
        assert 1 <= seconds <= 300
        yield


class FakeExplorer:
    def __init__(self) -> None:
        self.ssh = FakeSSH()
        self.active = 0
        self.max_active = 0

    async def get_system_info(self) -> dict[str, Any]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return {"success": True, "hostname": "mock-router"}

    async def test_connection(self) -> dict[str, Any]:
        return {"success": True, "status": "connected"}

    def __getattr__(self, _: str) -> Any:
        async def generic(*args: Any) -> dict[str, Any]:
            return {"success": True, "args": list(args)}

        return generic


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[fn.__name__] = fn
            return fn

        return decorator


async def test_supported_and_active_catalogs_are_distinct(settings: Any) -> None:
    kernel = build_invocation_kernel(settings, FakeExplorer())
    supported = kernel.registry.supported()
    active = kernel.registry.active()
    assert len(supported) == 24
    assert len(active) == 19
    inactive_names = {item["name"] for item in supported if not item["active"]}
    assert inactive_names == {
        "restart_interface",
        "reload_network",
        "uci_set",
        "uci_commit",
        "reboot_device",
    }


async def test_inactive_write_fails_before_operation_lookup(settings: Any) -> None:
    kernel = build_invocation_kernel(settings, FakeExplorer())
    result = await kernel.invoke("uci_set", {"value": "x"})
    assert result.success is False
    assert result.error is not None
    assert result.error.code == "CAPABILITY_INACTIVE"


async def test_kernel_enforces_concurrency(settings: Any) -> None:
    explorer = FakeExplorer()
    kernel = build_invocation_kernel(settings, explorer)
    await asyncio.gather(
        kernel.invoke("get_router_info", {}),
        kernel.invoke("get_router_info", {}),
    )
    assert explorer.max_active == 1


async def test_registration_attaches_complete_manifests(settings: Any) -> None:
    mcp = FakeMCP()
    kernel = build_invocation_kernel(settings, FakeExplorer())
    register_openwrt_tools(mcp, kernel)
    assert len(mcp.tools) == 19
    assert set(mcp.tools) == set(kernel.registry.active_names())
    for name, fn in mcp.tools.items():
        manifest = fn.__manifest__
        assert manifest["name"] == name
        assert "confidentiality" in manifest
        assert "operational_impact" in manifest
        assert manifest["retryable"] is False
        assert manifest["idempotent"] is False
        assert manifest["reversible"] is False
        assert manifest["max_response_bytes"] > 0
        assert fn.__doc__.startswith(f"[{manifest['risk']}]")

    for manifest in kernel.registry.supported():
        if not manifest["active"]:
            assert manifest["requires_confirmation"] is False


async def test_capability_discovery_declares_l1_sdk_and_protocol(settings: Any) -> None:
    kernel = build_invocation_kernel(settings, FakeExplorer())
    result = await kernel.invoke("describe_router_capabilities", {})
    assert result.success is True
    assert result.data["profile"] == "l1-local-read-only-stdio"
    assert result.data["sdk_family"] == "official-python-mcp"
    assert result.data["sdk_version"] == "2.0.0"
    assert result.data["protocol_versions"] == ["2026-07-28", "2025-11-25"]
    assert result.data["supported_transports"] == ["stdio"]
    assert result.data["active_transports"] == ["stdio"]


async def test_mocked_application_invocation(settings: Any) -> None:
    kernel = build_invocation_kernel(settings, FakeExplorer())
    result = await kernel.invoke("get_router_info", {})
    assert result.success is True
    assert result.data["hostname"] == "mock-router"
    assert result.meta is not None
    assert result.meta["target"].startswith("ssh:root@")
