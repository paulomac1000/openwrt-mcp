from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest
from mcp.types import CallToolResult

from openwrt_mcp.application import (
    CapabilityManifest,
    CapabilityRegistry,
    InputField,
    InputSchema,
    InvocationKernel,
)
from openwrt_mcp.mock_explorer import MockOpenWRTExplorer
from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.registration import (
    _invoke_for_mcp,
    build_invocation_kernel,
    register_openwrt_tools,
)


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
        log_level="INFO",
        enable_audit_logging=False,
        audit_log_file=Path("/tmp/audit"),
        mcp_transport="stdio",
        mock_mode=True,
    )


def manifest(
    name: str,
    *,
    timeout_ms: int = 1_000,
    concurrency_group: str | None = None,
    input_schema: InputSchema | None = None,
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
        input_schema=input_schema or InputSchema(),
    )


class FakeMCP:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[fn.__name__] = fn
            return fn

        return decorator


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
        registry=CapabilityRegistry({"first": manifest("first"), "second": manifest("second")}),
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


@pytest.mark.asyncio
async def test_kernel_rejects_missing_unknown_wrong_type_and_range() -> None:
    calls: list[dict[str, Any]] = []

    async def operation(**values: Any) -> dict[str, Any]:
        calls.append(values)
        return {"success": True}

    schema = InputSchema(
        {
            "host": InputField((str,), required=True, max_length=253),
            "count": InputField((int,), default=4, minimum=1, maximum=5),
        }
    )
    kernel = InvocationKernel(
        registry=CapabilityRegistry({"ping": manifest("ping", input_schema=schema)}),
        operations={"ping": operation},
        target_identity="router",
    )
    cases = [
        ({}, "Missing required"),
        ({"host": "example.com", "unknown": 1}, "Unknown argument"),
        ({"host": 42}, "host must be str"),
        ({"host": "example.com", "count": True}, "integer"),
        ({"host": "example.com", "count": 6}, "at most"),
    ]
    for arguments, message in cases:
        result = await kernel.invoke("ping", arguments)
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "INVALID_PARAM"
        assert message in result.error.message
    assert calls == []

    result = await kernel.invoke("ping", {"host": "example.com"})
    assert result.success is True
    assert calls == [{"host": "example.com", "count": 4}]


def test_manifest_exposes_closed_json_schema() -> None:
    registry = build_invocation_kernel(
        mock_settings(),
        MockOpenWRTExplorer(),
    ).registry
    schema = registry.get("ping_host").as_dict()["input_schema"]
    assert schema["required"] == ["host"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["count"]["maximum"] == 5


def test_public_mcp_signatures_match_kernel_input_contracts() -> None:
    kernel = build_invocation_kernel(mock_settings(), MockOpenWRTExplorer())
    mcp = FakeMCP()
    register_openwrt_tools(mcp, kernel)
    assert set(mcp.tools) == set(kernel.registry.active_names())
    for name, fn in mcp.tools.items():
        public = set(inspect.signature(fn).parameters)
        governed = set(kernel.registry.get(name).input_schema.fields)
        assert public == governed, name
        assert "timeout_seconds" not in public


@pytest.mark.asyncio
async def test_all_active_mock_contracts() -> None:
    kernel = build_invocation_kernel(mock_settings(), MockOpenWRTExplorer())
    arguments = {
        "read_router_uci_config": {"config_name": "network"},
        "search_router_logs": {"search_term": "mock"},
        "search_dhcp_logs": {"search_term": "mock"},
        "get_device_dhcp_details": {"mac_address": "02:00:00:00:00:01"},
        "ping_host": {"host": "example.com"},
        "traceroute_host": {"host": "example.com"},
        "nslookup_host": {"host": "example.com"},
    }
    for name in kernel.registry.active_names():
        result = await kernel.invoke(name, arguments.get(name, {}))
        assert result.success, (name, result.error)
        assert isinstance(result.data, dict)


@pytest.mark.asyncio
async def test_controlled_failure_is_sanitized_call_tool_result() -> None:
    async def bad() -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": "UPSTREAM_FAILURE",
                "message": "password=router-secret",
            },
        }

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"bad": manifest("bad")}),
        operations={"bad": bad},
        target_identity="router",
    )
    result = await _invoke_for_mcp(kernel, "bad", {})
    assert isinstance(result, CallToolResult)
    assert result.is_error is True
    rendered = "\n".join(str(block.text) for block in result.content)
    assert "router-secret" not in rendered
    assert "<REDACTED>" in rendered
