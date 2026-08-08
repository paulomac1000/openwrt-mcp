"""Version-bounded compatibility shims for the official MCP Python SDK."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

SUPPORTED_MCP_SDK_VERSION = "2.0.0"


def _installed_mcp_version() -> str:
    try:
        return version("mcp")
    except PackageNotFoundError as exc:  # pragma: no cover - packaging invariant
        raise RuntimeError("official MCP SDK is not installed") from exc


def enforce_strict_input_schema(mcp: Any, name: str) -> None:
    """Tighten MCP 2.0.0's generated Pydantic tool model to reject extras.

    MCP 2.0.0 exposes no public registration option for ``extra='forbid'``.
    Keep the private-SDK dependency isolated here and fail closed if either the
    installed SDK version or the expected internal registration model changes.
    Test doubles outside the official ``mcp.*`` namespace are intentionally
    ignored so unit tests do not need to emulate private SDK internals.
    """

    if not type(mcp).__module__.startswith("mcp."):
        return

    installed = _installed_mcp_version()
    if installed != SUPPORTED_MCP_SDK_VERSION:
        raise RuntimeError(
            "strict MCP input compatibility shim only supports "
            f"mcp=={SUPPORTED_MCP_SDK_VERSION}; found {installed}"
        )

    tool_manager = getattr(mcp, "_tool_manager", None)
    get_tool = getattr(tool_manager, "get_tool", None)
    if not callable(get_tool):
        raise RuntimeError("MCP SDK tool manager unavailable for strict input validation")
    tool = get_tool(name)
    if tool is None:
        raise RuntimeError(f"MCP SDK did not register tool {name!r}")

    try:
        arg_model = tool.fn_metadata.arg_model
        arg_model.model_config["extra"] = "forbid"
        arg_model.model_rebuild(force=True)
        tool.parameters = arg_model.model_json_schema(by_alias=True)
    except (AttributeError, KeyError, TypeError) as exc:
        raise RuntimeError("MCP SDK argument model changed unexpectedly") from exc

    if tool.parameters.get("additionalProperties") is not False:
        raise RuntimeError(f"strict MCP input schema was not applied to {name!r}")
