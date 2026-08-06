from __future__ import annotations

from pathlib import Path

import pytest

from openwrt_mcp.settings import Settings, reset_settings_for_tests


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    key = tmp_path / "id_ed25519"
    known_hosts = tmp_path / "known_hosts"
    key.write_text("fake", encoding="utf-8")
    known_hosts.write_text("router ssh-ed25519 fake", encoding="utf-8")
    return Settings(
        openwrt_host="192.0.2.10",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=key,
        openwrt_password=None,
        openwrt_known_hosts=known_hosts,
        ssh_timeout=30,
        health_port=19094,
        rest_api_port=19096,
        enable_rest_api=False,
        log_level="INFO",
        enable_audit_logging=True,
        audit_log_file=tmp_path / "audit.log",
        rest_auth_token=None,
        max_request_body_bytes=1024,
        allowed_origins=(),
        mcp_transport="stdio",
        mock_mode=False,
    )
