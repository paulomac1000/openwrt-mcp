from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from openwrt_mcp.settings import Settings, load_settings


def test_settings_are_frozen(settings: Settings) -> None:
    with pytest.raises(FrozenInstanceError):
        settings.openwrt_host = "example.test"  # type: ignore[misc]


def test_wildcard_origin_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "*")
    with pytest.raises(ValueError, match="must not contain"):
        Settings.from_env()


def test_legacy_sse_transport_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    with pytest.raises(ValueError, match="Only stdio"):
        Settings.from_env()


def test_settings_snapshot_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENWRT_HOST", "192.0.2.1")
    first = load_settings()
    monkeypatch.setenv("OPENWRT_HOST", "192.0.2.2")
    assert load_settings() is first
    assert first.openwrt_host == "192.0.2.1"
