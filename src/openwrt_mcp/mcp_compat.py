"""Version-bounded compatibility shims for the official MCP Python SDK."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Any

SUPPORTED_MCP_SDK_VERSION = "2.0.0"


def _installed_mcp_version() -> str:
    try:
        return version("mcp")
    except PackageNotFoundError as exc:  # pragma: no cover - packaging invariant
        raise RuntimeError("official MCP SDK is not installed") from exc


def enforce_strict_input_schema(
    mcp: Any,
    name: str,
    expected_schema: Mapping[str, Any],
) -> None:
    """Bind MCP 2.0.0 registration to the kernel-owned closed input schema.

    MCP 2.0.0 exposes no public registration option for ``extra='forbid'`` and
    derives its advertised schema from the Python wrapper rather than the
    transport-independent kernel manifest. Keep that private-SDK dependency
    isolated here, fail closed if the expected internals move, and publish the
    exact kernel schema after verifying the SDK model exposes the same fields.

    Test doubles outside the official ``mcp.*`` namespace are intentionally
    ignored so deterministic unit tests do not need to emulate private SDK
    internals.
    """

    if not type(mcp).__module__.startswith("mcp."):
        return

    installed = _installed_mcp_version()
    if installed != SUPPORTED_MCP_SDK_VERSION:
        raise RuntimeError(
            "strict MCP input compatibility shim only supports "
            f"mcp=={SUPPORTED_MCP_SDK_VERSION}; found {installed}"
        )

    if (
        expected_schema.get("type") != "object"
        or expected_schema.get("additionalProperties") is not False
    ):
        raise RuntimeError(f"kernel input schema for {name!r} is not closed")

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
        generated = arg_model.model_json_schema(by_alias=True)
    except (AttributeError, KeyError, TypeError) as exc:
        raise RuntimeError("MCP SDK argument model changed unexpectedly") from exc

    expected_properties = set(expected_schema.get("properties", {}))
    generated_properties = set(generated.get("properties", {}))
    if generated_properties != expected_properties:
        raise RuntimeError(f"MCP wrapper parameters for {name!r} disagree with the kernel schema")
    expected_required = set(expected_schema.get("required", []))
    generated_required = set(generated.get("required", []))
    if generated_required != expected_required:
        raise RuntimeError(
            f"MCP wrapper required fields for {name!r} disagree with the kernel schema"
        )

    tool.parameters = copy.deepcopy(dict(expected_schema))
    if tool.parameters.get("additionalProperties") is not False:
        raise RuntimeError(f"strict MCP input schema was not applied to {name!r}")
