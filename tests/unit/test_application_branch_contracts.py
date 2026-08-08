from __future__ import annotations

from typing import Any

import pytest

from openwrt_mcp.application import (
    CapabilityManifest,
    CapabilityRegistry,
    InputField,
    InputSchema,
    InvocationKernel,
    KernelError,
    KernelResult,
    decode_kernel_response,
)
from openwrt_mcp.validators import ValidationError


def manifest(name: str, **overrides: Any) -> CapabilityManifest:
    values: dict[str, Any] = {
        "name": name,
        "version": "1",
        "risk": "READ",
        "side_effects": "read",
        "confidentiality": "internal",
        "operational_impact": "none",
        "cost": "cheap",
        "idempotent": False,
        "retryable": False,
        "concurrent_safe": True,
        "timeout_ms": 1_000,
        "requires_confirmation": False,
        "reversible": False,
    }
    values.update(overrides)
    return CapabilityManifest(**values)


def test_input_field_schema_and_validation_cover_optional_branches() -> None:
    union = InputField((str, type(None)), default=None, max_length=5)
    assert union.as_json_schema() == {
        "type": ["string", "null"],
        "maxLength": 5,
        "default": None,
    }
    assert union.validate("value", None) is None
    with pytest.raises(ValidationError, match="at most 5"):
        union.validate("value", "123456")

    numeric = InputField((int, float), minimum=1, maximum=2)
    assert numeric.as_json_schema()["type"] == ["integer", "number"]
    assert numeric.validate("number", 1.5) == 1.5
    with pytest.raises(ValidationError, match="at least 1"):
        numeric.validate("number", 0)
    with pytest.raises(ValidationError, match="at most 2"):
        numeric.validate("number", 3)
    with pytest.raises(ValidationError, match="int or float"):
        numeric.validate("number", "1")


def test_input_schema_accepts_optional_missing_field_without_default() -> None:
    schema = InputSchema({"optional": InputField((str,))})
    assert schema.validate({}) == {}
    with pytest.raises(ValidationError, match="JSON object"):
        schema.validate([])


def test_kernel_error_and_result_optional_fields_are_explicit() -> None:
    plain = KernelError("E", "message").as_dict()
    assert "suggestion" not in plain
    suggested = KernelError("E", "message", suggestion="retry later").as_dict()
    assert suggested["suggestion"] == "retry later"

    failed = KernelResult.failed("E", "message", suggestion="password=secret")
    assert failed.error is not None
    assert failed.error.suggestion == "password=<REDACTED>"
    payload = KernelResult(success=False).as_dict()
    assert payload["error"]["code"] == "INTERNAL"
    assert "_meta" not in payload


def test_kernel_rejects_missing_and_orphaned_operation_registration() -> None:
    registry = CapabilityRegistry({"probe": manifest("probe")})
    with pytest.raises(ValueError, match="missing=\['probe'\]"):
        InvocationKernel(registry=registry, operations={}, target_identity="router")

    async def orphan() -> dict[str, Any]:
        return {"success": True}

    with pytest.raises(ValueError, match="orphaned=\['orphan'\]"):
        InvocationKernel(
            registry=CapabilityRegistry({}),
            operations={"orphan": orphan},
            target_identity="router",
        )


@pytest.mark.asyncio
async def test_kernel_handles_registration_drift_and_unstructured_upstream_failure() -> None:
    async def operation() -> dict[str, Any]:
        return {"success": False, "error": "router refused request"}

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"probe": manifest("probe")}),
        operations={"probe": operation},
        target_identity="router",
    )
    result = await kernel.invoke("probe", {})
    assert result.error is not None
    assert result.error.code == "UPSTREAM_FAILURE"

    kernel._operations.clear()
    drift = await kernel.invoke("probe", {})
    assert drift.error is not None
    assert drift.error.code == "REGISTRATION_ERROR"


@pytest.mark.asyncio
async def test_kernel_rejects_non_serializable_success_payload() -> None:
    async def operation() -> dict[str, Any]:
        return {"success": True, "value": object()}

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"probe": manifest("probe")}),
        operations={"probe": operation},
        target_identity="router",
    )
    result = await kernel.invoke("probe", {})
    assert result.error is not None
    assert result.error.code == "INTERNAL"
    assert result.error.message == "Operation returned a non-serializable response"


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("AUTHENTICATION_REQUIRED", 401),
        ("AUTHORIZATION_DENIED", 403),
        ("CAPABILITY_INACTIVE", 409),
        ("UNRECOGNIZED", 500),
    ],
)
def test_decode_kernel_response_covers_security_and_fallback_statuses(
    code: str, status: int
) -> None:
    result = KernelResult.failed(code, "message")
    assert decode_kernel_response(result)[0] == status
    assert decode_kernel_response(KernelResult.ok({"ok": True}, meta={}))[0] == 200
