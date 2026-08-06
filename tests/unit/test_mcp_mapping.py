from __future__ import annotations

import sys
import types
from typing import Any

import pytest

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
async def test_mcp_mapping_returns_structured_success_and_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TextContent:
        def __init__(self, *, type: str, text: str) -> None:
            self.type = type
            self.text = text

    class CallToolResult:
        def __init__(
            self,
            *,
            content: list[Any],
            structured_content: dict[str, Any] | None = None,
            is_error: bool = False,
        ) -> None:
            self.content = content
            self.structured_content = structured_content
            self.is_error = is_error

    package = types.ModuleType("mcp")
    module = types.ModuleType("mcp.types")
    module.CallToolResult = CallToolResult  # type: ignore[attr-defined]
    module.TextContent = TextContent  # type: ignore[attr-defined]
    package.types = module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp", package)
    monkeypatch.setitem(sys.modules, "mcp.types", module)

    async def good() -> dict[str, Any]:
        return {"success": True, "value": 1}

    async def bad() -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": "UPSTREAM_FAILURE",
                "message": "safe failure",
            },
        }

    kernel = InvocationKernel(
        registry=CapabilityRegistry(
            {"good": manifest("good"), "bad": manifest("bad")}
        ),
        operations={"good": good, "bad": bad},
        target_identity="router",
    )
    success = await _invoke_for_mcp(kernel, "good", {})
    failure = await _invoke_for_mcp(kernel, "bad", {})
    assert success.is_error is False
    assert success.structured_content["success"] is True
    assert failure.is_error is True
    assert failure.structured_content is None
    assert "safe failure" in failure.content[0].text


@pytest.mark.asyncio
async def test_mcp_mapping_has_offline_fallback_without_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openwrt_mcp.application import ToolExecutionError

    monkeypatch.delitem(sys.modules, "mcp", raising=False)
    monkeypatch.delitem(sys.modules, "mcp.types", raising=False)

    async def good() -> dict[str, Any]:
        return {"success": True, "value": 1}

    async def bad() -> dict[str, Any]:
        return {
            "success": False,
            "error": {"code": "UPSTREAM_FAILURE", "message": "safe"},
        }

    kernel = InvocationKernel(
        registry=CapabilityRegistry(
            {"good": manifest("good"), "bad": manifest("bad")}
        ),
        operations={"good": good, "bad": bad},
        target_identity="router",
    )
    success = await _invoke_for_mcp(kernel, "good", {})
    assert success["success"] is True
    with pytest.raises(ToolExecutionError, match="UPSTREAM_FAILURE"):
        await _invoke_for_mcp(kernel, "bad", {})
