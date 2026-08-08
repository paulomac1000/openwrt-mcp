from __future__ import annotations

from typing import Any

import pytest

from openwrt_mcp import mcp_compat


class FakeArgModel:
    model_config: dict[str, Any] = {"extra": "ignore"}
    rebuilt = False
    schema: dict[str, Any] = {}

    @classmethod
    def model_rebuild(cls, *, force: bool) -> None:
        cls.rebuilt = force

    @classmethod
    def model_json_schema(cls, *, by_alias: bool) -> dict[str, Any]:
        assert by_alias is True
        return cls.schema


class FakeMetadata:
    arg_model = FakeArgModel


class FakeTool:
    fn_metadata = FakeMetadata()
    parameters: dict[str, Any] = {}


class FakeManager:
    def __init__(self, tool: FakeTool | None = None) -> None:
        self.tool = tool or FakeTool()

    def get_tool(self, name: str) -> FakeTool | None:
        return self.tool if name == "ping_host" else None


OfficialLikeMCP = type("OfficialLikeMCP", (), {"__module__": "mcp.server"})


def expected_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "host": {"type": "string", "maxLength": 253},
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "default": 4,
            },
        },
        "required": ["host"],
        "additionalProperties": False,
    }


def official_like(tool: FakeTool | None = None) -> Any:
    instance = OfficialLikeMCP()
    instance._tool_manager = FakeManager(tool)
    return instance


def generated_schema(*, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "host": {"type": "string"},
            "count": {"type": "integer", "default": 4},
        },
        "required": ["host"] if required is None else required,
    }


def test_private_sdk_compatibility_is_version_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_compat, "_installed_mcp_version", lambda: "2.0.1")
    with pytest.raises(RuntimeError, match="only supports mcp==2.0.0"):
        mcp_compat.enforce_strict_input_schema(
            official_like(),
            "ping_host",
            expected_schema(),
        )


def test_private_sdk_compatibility_publishes_exact_kernel_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeArgModel.model_config = {"extra": "ignore"}
    FakeArgModel.rebuilt = False
    FakeArgModel.schema = generated_schema()
    monkeypatch.setattr(mcp_compat, "_installed_mcp_version", lambda: "2.0.0")
    mcp = official_like()
    expected = expected_schema()

    mcp_compat.enforce_strict_input_schema(mcp, "ping_host", expected)

    tool = mcp._tool_manager.get_tool("ping_host")
    assert tool is not None
    assert FakeArgModel.model_config["extra"] == "forbid"
    assert FakeArgModel.rebuilt is True
    assert tool.parameters == expected
    assert tool.parameters is not expected


def test_private_sdk_compatibility_fails_closed_on_wrapper_field_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeArgModel.schema = {
        "type": "object",
        "properties": {"host": {}, "unexpected": {}},
        "required": ["host"],
    }
    monkeypatch.setattr(mcp_compat, "_installed_mcp_version", lambda: "2.0.0")
    with pytest.raises(RuntimeError, match="parameters.*disagree"):
        mcp_compat.enforce_strict_input_schema(
            official_like(),
            "ping_host",
            expected_schema(),
        )


def test_private_sdk_compatibility_fails_closed_on_required_field_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeArgModel.schema = generated_schema(required=[])
    monkeypatch.setattr(mcp_compat, "_installed_mcp_version", lambda: "2.0.0")
    with pytest.raises(RuntimeError, match="required fields.*disagree"):
        mcp_compat.enforce_strict_input_schema(
            official_like(),
            "ping_host",
            expected_schema(),
        )


def test_private_sdk_compatibility_rejects_open_kernel_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_compat, "_installed_mcp_version", lambda: "2.0.0")
    schema = expected_schema()
    schema["additionalProperties"] = True
    with pytest.raises(RuntimeError, match="not closed"):
        mcp_compat.enforce_strict_input_schema(official_like(), "ping_host", schema)


def test_non_sdk_test_double_is_not_forced_to_emulate_private_internals() -> None:
    class FakeMCP:
        pass

    mcp_compat.enforce_strict_input_schema(FakeMCP(), "ping_host", expected_schema())
