from __future__ import annotations

import importlib
import inspect

import pytest


_EXPECTED_LAB_TESTS = {
    "test_real_router_wrong_host_key_never_opens_command_session",
    "test_real_router_official_mcp_read_smoke",
    "test_real_router_cancellation_closes_session_and_kills_remote_command",
    "test_real_router_timeout_closes_session_and_kills_remote_command",
    "test_real_router_response_byte_limit_is_enforced",
}


def test_real_router_acceptance_gate_has_owned_executable_cases() -> None:
    module = importlib.import_module("tests.integration.test_real_router_acceptance")
    discovered = {
        name
        for name, value in vars(module).items()
        if name.startswith("test_real_router_") and inspect.iscoroutinefunction(value)
    }
    assert discovered == _EXPECTED_LAB_TESTS


def test_only_deferred_write_profile_is_an_explicit_not_implemented_placeholder() -> None:
    module = importlib.import_module("tests.integration.test_real_router_todos")
    function = module.test_real_router_write_authorization_and_approval_workflow
    skip_reasons = [
        mark.kwargs.get("reason", "")
        for mark in getattr(function, "pytestmark", [])
        if mark.name == "skip"
    ]
    assert len(skip_reasons) == 1
    assert skip_reasons[0].startswith("NOT_IMPLEMENTED(")
    with pytest.raises(NotImplementedError, match="future authenticated write profile"):
        function()
