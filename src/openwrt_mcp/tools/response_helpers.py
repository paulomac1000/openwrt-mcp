"""Response format helpers for MCP tools — L1+ standard compliance."""

import json
from typing import Any


def _success_response(data: Any, _meta: dict[str, Any] | None = None) -> str:
    """Format a successful tool response with optional _meta envelope."""
    response: dict[str, Any] = {"success": True, "data": data}
    if _meta is not None:
        response["_meta"] = _meta
    return json.dumps(response)


def _error_response(error: str) -> str:
    """Format an error tool response."""
    return json.dumps({"success": False, "error": error})


def _error_response_extended(
    code: str,
    message: str,
    retryable: bool,
    suggestion: str | None = None,
    available_names: list[str] | None = None,
) -> str:
    """Format an extended L2+ error response with structured fields."""
    error: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    if suggestion:
        error["suggestion"] = suggestion
    if available_names:
        error["available_names"] = available_names[:50]
    return json.dumps({"success": False, "error": error})


def _error_dict_extended(
    code: str,
    message: str,
    retryable: bool,
    suggestion: str | None = None,
    available_names: list[str] | None = None,
) -> dict[str, Any]:
    """Return an extended error dict (for internal functions that return dicts)."""
    err: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    if suggestion:
        err["suggestion"] = suggestion
    if available_names:
        err["available_names"] = available_names[:50]
    return {"success": False, "error": err}
