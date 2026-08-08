_EXPECTED_LAB_TESTS = {
    "test_real_router_wrong_host_key_never_opens_command_session",
    "test_real_router_official_mcp_read_smoke",
    "test_real_router_cancellation_closes_session_and_kills_remote_command",
    "test_real_router_timeout_closes_session_and_kills_remote_command",
    "test_real_router_response_byte_limit_is_enforced",
}


def _load(module_name: str):
    return __import__(module_name, fromlist=["*"])


def test_real_router_acceptance_gate_has_owned_executable_cases() -> None:
    module = _load("tests.integration.test_real_router_acceptance")
    discovered = {
        name
        for name, value in vars(module).items()
        if name.startswith("test_real_router_")
        and callable(value)
        and hasattr(value, "__code__")
        and bool(value.__code__.co_flags & 0x80)
    }
    assert discovered == _EXPECTED_LAB_TESTS


def test_only_deferred_write_profile_is_an_explicit_not_implemented_placeholder() -> None:
    module = _load("tests.integration.test_real_router_todos")
    function = module.test_real_router_write_authorization_and_approval_workflow
    skip_reasons = [
        mark.kwargs.get("reason", "")
        for mark in getattr(function, "pytestmark", [])
        if mark.name == "skip"
    ]
    assert len(skip_reasons) == 1
    assert skip_reasons[0].startswith("NOT_IMPLEMENTED(")
    try:
        function()
    except NotImplementedError as exc:
        assert "future authenticated write profile" in str(exc)
    else:
        raise AssertionError("write-profile placeholder must raise NotImplementedError")
