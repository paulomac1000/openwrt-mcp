from __future__ import annotations

from pathlib import Path

import pytest

from openwrt_mcp.settings import Settings, _bool_env, _int_env, load_settings


def test_environment_helpers_cover_defaults_truthy_invalid_and_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLAG", raising=False)
    assert _bool_env("FLAG", True) is True
    monkeypatch.setenv("FLAG", " yes ")
    assert _bool_env("FLAG") is True

    monkeypatch.setenv("NUMBER", "not-a-number")
    with pytest.raises(ValueError, match="must be an integer"):
        _int_env("NUMBER", 1, minimum=1, maximum=2)
    monkeypatch.setenv("NUMBER", "3")
    with pytest.raises(ValueError, match="between 1 and 2"):
        _int_env("NUMBER", 1, minimum=1, maximum=2)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("OPENWRT_HOST", " ", "OPENWRT_HOST"),
        ("OPENWRT_USER", " ", "OPENWRT_USER"),
    ],
)
def test_empty_required_identity_is_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, message: str
) -> None:
    monkeypatch.setenv("OPENWRT_MOCK_MODE", "1")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        Settings.from_env()


def test_real_mode_rejects_key_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    known = tmp_path / "known_hosts"
    known.write_text("host key", encoding="utf-8")
    key_directory = tmp_path / "key-directory"
    key_directory.mkdir()
    monkeypatch.setenv("OPENWRT_MOCK_MODE", "0")
    monkeypatch.setenv("OPENWRT_KNOWN_HOSTS", str(known))
    monkeypatch.setenv("OPENWRT_SSH_KEY", str(key_directory))
    with pytest.raises(ValueError, match="regular file"):
        Settings.from_env()


def test_force_reload_replaces_cached_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENWRT_MOCK_MODE", "1")
    monkeypatch.setenv("OPENWRT_HOST", "first.test")
    first = load_settings(force=True)
    monkeypatch.setenv("OPENWRT_HOST", "second.test")
    second = load_settings(force=True)
    assert second is not first
    assert second.openwrt_host == "second.test"
