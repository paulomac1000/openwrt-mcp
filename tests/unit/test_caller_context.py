from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from openwrt_mcp.application import CapabilityManifest, CapabilityRegistry, InvocationKernel
from openwrt_mcp.observability import (
    CallerContext,
    get_caller_context,
    process_caller_context,
    request_context,
)
from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.ssh_client import SSHConnection


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        name="probe",
        version="1",
        risk="READ",
        side_effects="read",
        confidentiality="internal",
        operational_impact="none",
        cost="cheap",
        idempotent=False,
        retryable=False,
        concurrent_safe=True,
        timeout_ms=1_000,
        requires_confirmation=False,
        reversible=False,
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        openwrt_host="router.local",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=tmp_path / "key",
        openwrt_password=None,
        openwrt_known_hosts=tmp_path / "known_hosts",
        insecure_skip_host_key_check=False,
        ssh_timeout=30,
        health_port=9094,
        log_level="INFO",
        enable_audit_logging=True,
        audit_log_file=tmp_path / "audit.log",
        mcp_transport="stdio",
        mock_mode=True,
    )


def test_process_caller_is_explicit_and_context_resets() -> None:
    process = process_caller_context()
    assert process.principal.startswith(("os-uid:", "process-user:"))
    assert process.boundary == "local-process"
    assert get_caller_context().principal == "system:internal"

    caller = CallerContext("os-uid:4242")
    with request_context("req-1", caller=caller):
        assert get_caller_context() == caller
    assert get_caller_context().principal == "system:internal"


async def test_caller_context_does_not_cross_tasks() -> None:
    seen: dict[str, list[str]] = {"a": [], "b": []}

    async def worker(name: str) -> None:
        caller = CallerContext(f"principal:{name}")
        with request_context(name, caller=caller):
            seen[name].append(get_caller_context().principal)
            await asyncio.sleep(0)
            seen[name].append(get_caller_context().principal)

    await asyncio.gather(worker("a"), worker("b"))
    assert seen == {
        "a": ["principal:a", "principal:a"],
        "b": ["principal:b", "principal:b"],
    }


async def test_kernel_meta_records_caller_separately_from_target() -> None:
    async def operation() -> dict[str, Any]:
        return {"success": True}

    default = CallerContext("os-uid:1000")
    kernel = InvocationKernel(
        registry=CapabilityRegistry({"probe": _manifest()}),
        operations={"probe": operation},
        target_identity="ssh:root@router.local:22",
        default_caller=default,
    )
    result = await kernel.invoke("probe", {}, caller=CallerContext("os-uid:2000"))
    assert result.success is True
    assert result.meta is not None
    assert result.meta["caller"] == {
        "principal": "os-uid:2000",
        "boundary": "local-process",
    }
    assert result.meta["target"] == "ssh:root@router.local:22"


def test_ssh_audit_records_caller_and_target_separately(tmp_path: Path) -> None:
    ssh = SSHConnection(_settings(tmp_path))
    with request_context("req-audit", caller=CallerContext("os-uid:4242")):
        ssh._log_audit("ubus call system board")

    rendered = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "req-audit" in rendered
    assert "caller=os-uid:4242" in rendered
    assert "target=root@router.local" in rendered
