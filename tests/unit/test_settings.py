from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from openwrt_mcp.settings import Settings, load_settings


def test_settings_are_frozen(settings: Settings) -> None:
    with pytest.raises(FrozenInstanceError):
        settings.openwrt_host = "example.test"  # type: ignore[misc]


def test_legacy_sse_transport_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.delenv("OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK", raising=False)
    with pytest.raises(ValueError, match="OPENWRT_KNOWN_HOSTS"):
        Settings.from_env()


def _clear_real_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENWRT_MOCK_MODE",
        "OPENWRT_KNOWN_HOSTS",
        "OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK",
        "OPENWRT_SSH_KEY",
        "OPENWRT_PASSWORD",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_real_mode_rejects_nonexistent_known_hosts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_real_auth_env(monkeypatch)
    key = tmp_path / "key"
    key.write_text("x", encoding="utf-8")
    monkeypatch.setenv("OPENWRT_KNOWN_HOSTS", str(tmp_path / "missing"))
    monkeypatch.setenv("OPENWRT_SSH_KEY", str(key))
    with pytest.raises(ValueError, match="existing regular file"):
        Settings.from_env()


def test_real_mode_requires_existing_key_or_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_real_auth_env(monkeypatch)
    known = tmp_path / "known_hosts"
    known.write_text("x", encoding="utf-8")
    monkeypatch.setenv("OPENWRT_KNOWN_HOSTS", str(known))
    monkeypatch.setenv("OPENWRT_SSH_KEY", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="SSH authentication"):
        Settings.from_env()


def test_real_mode_accepts_password_without_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_real_auth_env(monkeypatch)
    known = tmp_path / "known_hosts"
    known.write_text("x", encoding="utf-8")
    monkeypatch.setenv("OPENWRT_KNOWN_HOSTS", str(known))
    monkeypatch.setenv("OPENWRT_SSH_KEY", str(tmp_path / "missing"))
    monkeypatch.setenv("OPENWRT_PASSWORD", "secret")
    result = Settings.from_env()
    assert result.openwrt_password == "secret"


def test_log_level_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_real_auth_env(monkeypatch)
    monkeypatch.setenv("OPENWRT_MOCK_MODE", "1")
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings.from_env()
