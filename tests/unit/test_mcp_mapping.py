from __future__ import annotations

from typing import Any

import pytest
from mcp.types import CallToolResult

from openwrt_mcp.application import CapabilityManifest, CapabilityRegistry, InvocationKernel
from openwrt_mcp.tools.registration import _invoke_for_mcp


def manifest(name: str) -> CapabilityManifest:
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
        timeout_ms=1_000,
        requires_confirmation=False,
        reversible=True,
    )


@pytest.mark.asyncio
async def test_mcp_mapping_returns_structured_success_and_tool_error() -> None:
    async def good() -> dict[str, Any]:
        return {"success": True, "value": 1}

    async def bad() -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": "UPSTREAM_FAILURE",
                "message": "password=router-secret",
            },
        }

    kernel = InvocationKernel(
        registry=CapabilityRegistry({"good": manifest("good"), "bad": manifest("bad")}),
        operations={"good": good, "bad": bad},
        target_identity="router",
    )
    success = await _invoke_for_mcp(kernel, "good", {})
    failure = await _invoke_for_mcp(kernel, "bad", {})

    assert isinstance(success, CallToolResult)
    assert success.is_error is False
    assert success.structured_content is not None
    assert success.structured_content["success"] is True
    assert isinstance(failure, CallToolResult)
    assert failure.is_error is True
    assert failure.structured_content is not None
    assert failure.structured_content["success"] is False
    assert failure.structured_content["error"]["code"] == "UPSTREAM_FAILURE"
    rendered = "\n".join(str(block.text) for block in failure.content)
    assert "router-secret" not in rendered
    assert "router-secret" not in str(failure.structured_content)
    assert "<REDACTED>" in rendered
