from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from openwrt_mcp.settings import Settings, load_settings


def test_settings_are_frozen(settings: Settings) -> None:
    with pytest.raises(FrozenInstanceError):
        settings.openwrt_host = "example.test"  # type: ignore[misc]


def test_legacy_sse_transport_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENWRT_MOCK_MODE", "1")
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    with pytest.raises(ValueError, match="Only stdio"):
        Settings.from_env()


def test_rest_configuration_is_not_part_of_runtime_settings() -> None:
    assert "enable_rest_api" not in Settings.__dataclass_fields__
    assert "rest_api_port" not in Settings.__dataclass_fields__
    assert "rest_auth_token" not in Settings.__dataclass_fields__


def test_settings_snapshot_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENWRT_MOCK_MODE", "1")
    monkeypatch.setenv("OPENWRT_HOST", "192.0.2.1")
    first = load_settings()
    monkeypatch.setenv("OPENWRT_HOST", "192.0.2.2")
    assert load_settings() is first
    assert first.openwrt_host == "192.0.2.1"


def test_real_mode_requires_known_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENWRT_MOCK_MODE", raising=False)
    monkeypatch.delenv("OPENWRT_KNOWN_HOSTS", raising=False)
    monkeypatch.delenv(
        "OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK",
        raising=False,
    )
    with pytest.raises(ValueError, match="OPENWRT_KNOWN_HOSTS"):
        Settings.from_env()
