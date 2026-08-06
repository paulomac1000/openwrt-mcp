from __future__ import annotations

import asyncio
import inspect
import os
from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.application import (
    CapabilityManifest,
    CapabilityRegistry,
    InvocationKernel,
    ToolExecutionError,
)
from openwrt_mcp.mock_explorer import MockOpenWRTExplorer
from openwrt_mcp.settings import Settings, reset_settings_for_tests
from openwrt_mcp.tools.registration import (
    _invoke_for_mcp,
    build_invocation_kernel,
    register_openwrt_tools,
)

BASE_ENV = {
    "OPENWRT_HOST": "192.0.2.1",
    "OPENWRT_USER": "root",
    "OPENWRT_SSH_KEY": "/tmp/test-key",
    "OPENWRT_KNOWN_HOSTS": "/tmp/known_hosts",
    "OPENWRT_MOCK_MODE": "0",
    "ENABLE_REST_API": "0",
}


def load_with(
    monkeypatch: pytest.MonkeyPatch,
    **values: str,
) -> Settings:
    reset_settings_for_tests()
    for name in list(os.environ):
        if name.startswith(("OPENWRT_", "MCP_", "ENABLE_REST_API")):
            monkeypatch.delenv(name, raising=False)
    for key, value in {**BASE_ENV, **values}.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env()


def test_real_mode_requires_host_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="OPENWRT_KNOWN_HOSTS"):
        load_with(monkeypatch, OPENWRT_KNOWN_HOSTS="")


def test_explicit_insecure_host_identity_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_with(
        monkeypatch,
        OPENWRT_KNOWN_HOSTS="",
        OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK="1",
    )
    assert settings.insecure_skip_host_key_check is True


def test_mock_mode_does_not_require_host_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_with(
        monkeypatch,
        OPENWRT_KNOWN_HOSTS="",
        OPENWRT_MOCK_MODE="1",
    )
    assert settings.mock_mode is True


def test_rest_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="MCP_REST_AUTH_TOKEN"):
        load_with(
            monkeypatch,
            ENABLE_REST_API="1",
            MCP_REST_AUTH_TOKEN="",
        )


def manifest(
    name: str,
    *,
    timeout_ms: int = 1_000,
    concurrency_group: str | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version="1",
        risk="READ",
        side_effects="read",
        confidentiality="internal",
        operational_impact="none",
        cost="cheap",
        idempotent=True,
        retryable=True,
        concurrent_safe=False,
        timeout_ms=timeout_ms,
        requires_confirmation=False,
        reversible=True,
        concurrency_group=concurrency_group,
    )


@pytest.mark.asyncio
async def test_different_tools_are_serialized_for_same_target() -> None:
    events: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def first() -> dict[str, Any]:
        events.append("first-start")
        first_started.set()
        await release_first.wait()
        events.append("first-end")
        return {"success": True}

    async def second() -> dict[str, Any]:
        events.extend(("second-start", "second-end"))
        return {"success": True}

    kernel = InvocationKernel(
        registry=CapabilityRegistry(
            {"first": manifest("first"), "second": manifest("second")}
        ),
        operations={"first": first, "second": second},
        target_identity="router-a",
    )
    task1 = asyncio.create_task(kernel.invoke("first", {}))
    await first_started.wait()
    task2 = asyncio.create_task(kernel.invoke("second", {}))
    await asyncio.sleep(0.02)
    assert events == ["first-start"]
    release_first.set()
    await asyncio.gather(task1, task2)
    assert events == [
        "first-start",
        "first-end",
        "second-start",
        "second-end",
    ]


@pytest.mark.asyncio
async def test_explicit_different_concurrency_groups_can_overlap() -> None:
    both_entered = asyncio.Event()
    entered = 0

    async def operation() -> dict[str, Any]:
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        return {"success": True}

    kernel = InvocationKernel(
        registry=CapabilityRegistry(
            {
                "first": manifest("first", concurrency_group="one"),
                "second": manifest("second", concurrency_group="two"),
            }
        ),
        operations={"first": operation, "second": operation},
        target_identity="router-a",
    )
    results = await asyncio.gather(
        kernel.invoke("first", {}),
        kernel.invoke("second", {}),
    )
    assert all(result.success for result in results)


@pytest.mark.asyncio
async def test_cancellation_releases_target_lock() -> None:
    entered = asyncio.Event()

    async def slow() -> dict[str, Any]:
        entered.set()
        await asyncio.sleep(10)
        return {"success": True}

    async def fast() -> dict[str, Any]:
        return {"success": True, "fast": True}

    kernel = InvocationKernel(
        registry=CapabilityRegistry(
            {
                "slow": manifest("slow", timeout_ms=20_000),
                "fast": manifest("fast"),
            }
        ),
        operations={"slow": slow, "fast": fast},
        target_identity="router-a",
    )
    task = asyncio.create_task(kernel.invoke("slow", {}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = await asyncio.wait_for(kernel.invoke("fast", {}), timeout=1)
    assert result.success


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def mock_settings() -> Settings:
    return Settings(
        openwrt_host="mock",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=Path("/tmp/key"),
        openwrt_password=None,
        openwrt_known_hosts=None,
        insecure_skip_host_key_check=False,
        ssh_timeout=30,
        health_port=9094,
        rest_api_port=9096,
        enable_rest_api=False,
        log_level="INFO",
        enable_audit_logging=False,
        audit_log_file=Path("/tmp/audit"),
        rest_auth_token=None,
        max_request_body_bytes=65_536,
        allowed_origins=(),
        mcp_transport="stdio",
        mock_mode=True,
    )


def test_public_mcp_schema_has_no_timeout_override() -> None:
    kernel = build_invocation_kernel(mock_settings(), MockOpenWRTExplorer())
    mcp = FakeMCP()
    register_openwrt_tools(mcp, kernel)
    assert len(mcp.tools) == 19
    for fn in mcp.tools.values():
        assert "timeout_seconds" not in inspect.signature(fn).parameters


@pytest.mark.asyncio
async def test_all_active_mock_contracts() -> None:
    kernel = build_invocation_kernel(mock_settings(), MockOpenWRTExplorer())
    arguments = {
        "read_router_uci_config": {"config_name": "network"},
        "search_router_logs": {"search_term": "mock"},
        "search_dhcp_logs": {"search_term": "mock"},
        "get_device_dhcp_details": {
            "mac_address": "02:00:00:00:00:01"
        },
        "ping_host": {"host": "example.com"},
        "traceroute_host": {"host": "example.com"},
        "nslookup_host": {"host": "example.com"},
    }
    required = {
        "test_router_connection": {"status", "host", "model", "release"},
        "get_router_info": {
            "model",
            "hostname",
            "openwrt_version",
            "kernel",
            "uptime_seconds",
            "memory_used_percent",
        },
        "get_router_wifi_status": {"interfaces_count", "interfaces", "note"},
        "get_router_dhcp_leases": {"leases_count", "leases"},
        "get_router_firewall_rules": {
            "firewall_type",
            "rules_preview",
            "full_output_truncated",
        },
        "read_router_uci_config": {
            "config_name",
            "entries_count",
            "sample",
        },
        "list_router_packages": {"packages_count", "packages_sample"},
        "get_router_logs": {"lines_count", "logs"},
        "search_router_logs": {"search_term", "results_count", "results"},
        "diagnose_router_connectivity": {"tests", "summary"},
        "get_dhcp_static_leases": {"static_leases_count", "leases"},
        "search_dhcp_logs": {"search_term", "events_found", "events"},
        "get_device_dhcp_details": {
            "device_identifier",
            "current_lease",
            "static_reservation",
            "has_static_reservation",
            "is_currently_connected",
            "recent_log_events",
            "note",
        },
        "get_router_context": {
            "device_id",
            "model",
            "uptime_seconds",
            "schema_version",
            "cpu_load_1min",
            "wifi_clients_total",
            "dhcp_leases_count",
            "kernel",
            "connectivity_health",
            "subsections",
        },
        "describe_router_capabilities": {
            "supported_tools",
            "active_tools",
            "total_supported",
            "total_active",
        },
        "ping_host": {"host", "output", "reachable"},
        "traceroute_host": {"host", "output"},
        "nslookup_host": {"host", "resolved", "output"},
        "wifi_scan": {"radio", "networks_found", "networks"},
    }
    for name in kernel.registry.active_names():
        result = await kernel.invoke(name, arguments.get(name, {}))
        assert result.success, name
        assert isinstance(result.data, dict)
        assert required[name] <= result.data.keys(), (
            name,
            required[name] - result.data.keys(),
        )


@pytest.mark.asyncio
async def test_tool_failure_is_sanitized_for_mcp_adapter() -> None:
    async def bad() -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": "UPSTREAM_FAILURE",
                "message": "password=hidden",
            },
        }

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"bad": manifest("bad")}),
        operations={"bad": bad},
        target_identity="router",
    )
    with pytest.raises(ToolExecutionError) as exc:
        await _invoke_for_mcp(kernel, "bad", {})
    assert "hidden" not in str(exc.value)
    assert "<REDACTED>" in str(exc.value)
