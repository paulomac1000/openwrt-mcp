from __future__ import annotations

from typing import Any

import pytest

from openwrt_mcp import mcp_compat


class FakeArgModel:
    model_config: dict[str, Any] = {"extra": "ignore"}
    rebuilt = False

    @classmethod
    def model_rebuild(cls, *, force: bool) -> None:
        cls.rebuilt = force

    @classmethod
    def model_json_schema(cls, *, by_alias: bool) -> dict[str, Any]:
        assert by_alias is True
        return {
            "type": "object",
            "additionalProperties": cls.model_config.get("extra") != "forbid",
        }


class FakeMetadata:
    arg_model = FakeArgModel


class FakeTool:
    fn_metadata = FakeMetadata()
    parameters: dict[str, Any] = {}


class FakeManager:
    def get_tool(self, name: str) -> FakeTool | None:
        return FakeTool() if name == "ping_host" else None


OfficialLikeMCP = type(
    "OfficialLikeMCP",
    (),
    {"__module__": "mcp.server", "_tool_manager": FakeManager()},
)


def test_private_sdk_compatibility_is_version_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_compat, "_installed_mcp_version", lambda: "2.0.1")
    with pytest.raises(RuntimeError, match="only supports mcp==2.0.0"):
        mcp_compat.enforce_strict_input_schema(OfficialLikeMCP(), "ping_host")


def test_private_sdk_compatibility_enforces_closed_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeArgModel.model_config = {"extra": "ignore"}
    FakeArgModel.rebuilt = False
    monkeypatch.setattr(mcp_compat, "_installed_mcp_version", lambda: "2.0.0")

    mcp_compat.enforce_strict_input_schema(OfficialLikeMCP(), "ping_host")

    assert FakeArgModel.model_config["extra"] == "forbid"
    assert FakeArgModel.rebuilt is True


def test_non_sdk_test_double_is_not_forced_to_emulate_private_internals() -> None:
    class FakeMCP:
        pass

    mcp_compat.enforce_strict_input_schema(FakeMCP(), "ping_host")
