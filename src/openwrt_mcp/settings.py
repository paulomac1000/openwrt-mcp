"""Typed, immutable process settings loaded before application composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in _TRUE_VALUES


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    openwrt_host: str
    openwrt_port: int
    openwrt_user: str
    openwrt_ssh_key: Path
    openwrt_password: str | None
    openwrt_known_hosts: Path | None
    ssh_timeout: int
    health_port: int
    rest_api_port: int
    enable_rest_api: bool
    log_level: str
    enable_audit_logging: bool
    audit_log_file: Path
    rest_auth_token: str | None
    max_request_body_bytes: int
    allowed_origins: tuple[str, ...]
    mcp_transport: str
    mock_mode: bool
    insecure_skip_host_key_check: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        host = os.getenv("OPENWRT_HOST", "192.168.1.1").strip()
        user = os.getenv("OPENWRT_USER", "root").strip()
        if not host:
            raise ValueError("OPENWRT_HOST must not be empty")
        if not user:
            raise ValueError("OPENWRT_USER must not be empty")

        known_hosts_raw = os.getenv("OPENWRT_KNOWN_HOSTS", "").strip()
        password = os.getenv("OPENWRT_PASSWORD") or None
        origins = tuple(
            item.strip()
            for item in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        )
        if "*" in origins:
            raise ValueError("MCP_ALLOWED_ORIGINS must not contain '*'")

        transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
        if transport != "stdio":
            raise ValueError(
                "Only stdio is enabled in the hardened profile. "
                "Streamable HTTP requires the pending authenticated transport adapter."
            )

        mock_mode = _bool_env("OPENWRT_MOCK_MODE", False)
        insecure_host_key = _bool_env("OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK", False)
        known_hosts = Path(known_hosts_raw) if known_hosts_raw else None
        if not mock_mode and known_hosts is None and not insecure_host_key:
            raise ValueError(
                "OPENWRT_KNOWN_HOSTS is required outside mock mode; "
                "set OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK=1 only for an explicit "
                "non-production exception"
            )

        enable_rest = _bool_env("ENABLE_REST_API", False)
        rest_token = os.getenv("MCP_REST_AUTH_TOKEN") or None
        if enable_rest and not rest_token:
            raise ValueError("MCP_REST_AUTH_TOKEN is required when REST is enabled")

        return cls(
            openwrt_host=host,
            openwrt_port=_int_env("OPENWRT_PORT", 22, minimum=1, maximum=65535),
            openwrt_user=user,
            openwrt_ssh_key=Path(
                os.getenv("OPENWRT_SSH_KEY", "/app/keys/openwrt_id_ed25519")
            ),
            openwrt_password=password,
            openwrt_known_hosts=known_hosts,
            insecure_skip_host_key_check=insecure_host_key,
            ssh_timeout=_int_env("SSH_TIMEOUT", 30, minimum=1, maximum=300),
            health_port=_int_env("HEALTH_PORT", 9094, minimum=1, maximum=65535),
            rest_api_port=_int_env("REST_API_PORT", 9096, minimum=1, maximum=65535),
            enable_rest_api=enable_rest,
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            enable_audit_logging=_bool_env("ENABLE_AUDIT_LOGGING", True),
            audit_log_file=Path(os.getenv("AUDIT_LOG_FILE", "/app/log/openwrt_mcp.log")),
            rest_auth_token=rest_token,
            max_request_body_bytes=_int_env(
                "MCP_MAX_REQUEST_BODY_BYTES", 65_536, minimum=1_024, maximum=1_048_576
            ),
            allowed_origins=origins,
            mcp_transport=transport,
            mock_mode=mock_mode,
        )


_snapshot: Settings | None = None
_snapshot_lock = Lock()


def load_settings(*, force: bool = False) -> Settings:
    global _snapshot
    with _snapshot_lock:
        if _snapshot is None or force:
            _snapshot = Settings.from_env()
        return _snapshot


def get_settings() -> Settings:
    return load_settings()


def reset_settings_for_tests() -> None:
    global _snapshot
    with _snapshot_lock:
        _snapshot = None
