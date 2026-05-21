"""Response format helpers for MCP tools — L1+ standard compliance."""

import json
from typing import Any

from openwrt_mcp.sanitizer import sanitize_response_data


def _success_response(data: Any, _meta: dict[str, Any] | None = None) -> str:
    """Format a successful tool response with optional _meta envelope.

    The payload is routed through ``sanitize_response_data()`` at this
    boundary (Canonical Template 4b) so a tool that forgets to sanitize
    cannot leak a credential to the agent.
    """
    response: dict[str, Any] = {"success": True, "data": sanitize_response_data(data)}
    if _meta is not None:
        response["_meta"] = _meta
    return json.dumps(response)


def _error_response(error: str) -> str:
    """Format an error tool response — error message is sanitized."""
    return json.dumps({"success": False, "error": sanitize_response_data(error)})


def _error_response_extended(
    code: str,
    message: str,
    retryable: bool,
    suggestion: str | None = None,
    available_names: list[str] | None = None,
) -> str:
    """Format an extended L2+ error response with structured fields — sanitized."""
    error: dict[str, Any] = {
        "code": code,
        "message": sanitize_response_data(message),
        "retryable": retryable,
    }
    if suggestion:
        error["suggestion"] = sanitize_response_data(suggestion)
    if available_names:
        error["available_names"] = sanitize_response_data(available_names)
    return json.dumps({"success": False, "error": error})


def _error_dict_extended(
    code: str,
    message: str,
    retryable: bool,
    suggestion: str | None = None,
    available_names: list[str] | None = None,
) -> dict[str, Any]:
    """Return an extended error dict (for internal functions that return dicts) — sanitized."""
    err: dict[str, Any] = {
        "code": code,
        "message": sanitize_response_data(message),
        "retryable": retryable,
    }
    if suggestion:
        err["suggestion"] = sanitize_response_data(suggestion)
    if available_names:
        err["available_names"] = sanitize_response_data(available_names)
    return {"success": False, "error": err}
