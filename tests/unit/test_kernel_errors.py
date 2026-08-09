from __future__ import annotations

import asyncio
from typing import Any

import pytest

from openwrt_mcp.application import (
    CapabilityManifest,
    CapabilityRegistry,
    InvocationKernel,
    decode_kernel_response,
)
from openwrt_mcp.validators import ValidationError


def manifest(name: str, **overrides: Any) -> CapabilityManifest:
    values = {
        "name": name,
        "version": "1",
        "risk": "READ",
        "side_effects": "read",
        "confidentiality": "internal",
        "operational_impact": "none",
        "cost": "cheap",
        "idempotent": True,
        "retryable": True,
        "concurrent_safe": True,
        "timeout_ms": 50,
        "requires_confirmation": False,
        "reversible": False,
        "max_response_bytes": 262_144,
    }
    values.update(overrides)
    return CapabilityManifest(**values)


async def test_unknown_capability_maps_to_rest_not_found() -> None:
    kernel = InvocationKernel(registry=CapabilityRegistry({}), operations={}, target_identity="x")
    result = await kernel.invoke("missing", {})
    status, payload = decode_kernel_response(result)
    assert status == 404
    assert payload["error"]["code"] == "NOT_FOUND"


async def test_upstream_structured_error_is_preserved_and_retry_gated() -> None:
    async def operation() -> dict[str, Any]:
        return {
            "success": False,
            "error": {"code": "UPSTREAM_FAILURE", "message": "safe", "retryable": True},
        }

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"read": manifest("read", retryable=False)}),
        operations={"read": operation},
        target_identity="x",
    )
    result = await kernel.invoke("read", {})
    assert result.error is not None
    assert result.error.retryable is False
    assert decode_kernel_response(result)[0] == 502


async def test_validation_and_internal_errors_are_classified() -> None:
    async def invalid() -> dict[str, Any]:
        raise ValidationError("bad value")

    async def broken() -> dict[str, Any]:
        raise RuntimeError("secret upstream body")

    registry = CapabilityRegistry({"invalid": manifest("invalid"), "broken": manifest("broken")})
    kernel = InvocationKernel(
        registry=registry,
        operations={"invalid": invalid, "broken": broken},
        target_identity="x",
    )
    invalid_result = await kernel.invoke("invalid", {})
    broken_result = await kernel.invoke("broken", {})
    assert invalid_result.error is not None and invalid_result.error.code == "INVALID_PARAM"
    assert broken_result.error is not None
    assert broken_result.error.message == "Internal server error"


@pytest.mark.parametrize("error", [TypeError("bug"), ValueError("bug")])
async def test_operation_programming_errors_are_internal(error: Exception) -> None:
    async def broken() -> dict[str, Any]:
        raise error

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"broken": manifest("broken")}),
        operations={"broken": broken},
        target_identity="x",
    )
    result = await kernel.invoke("broken", {})
    assert result.success is False
    assert result.error is not None
    assert result.error.code == "INTERNAL"
    assert result.error.message == "Internal server error"


async def test_timeout_is_bounded() -> None:
    async def slow() -> dict[str, Any]:
        await asyncio.sleep(1)
        return {"success": True}

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"slow": manifest("slow", timeout_ms=1)}),
        operations={"slow": slow},
        target_identity="x",
    )
    result = await kernel.invoke("slow", {})
    assert result.error is not None and result.error.code == "TIMEOUT"
    assert decode_kernel_response(result)[0] == 504


async def test_final_response_byte_limit_is_enforced() -> None:
    async def oversized() -> dict[str, Any]:
        return {"success": True, "payload": "x" * 2048}

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"read": manifest("read", max_response_bytes=512)}),
        operations={"read": oversized},
        target_identity="x",
    )
    result = await kernel.invoke("read", {})
    assert result.success is False
    assert result.error is not None
    assert result.error.code == "RESPONSE_TOO_LARGE"
    assert decode_kernel_response(result)[0] == 502
