"""Typed, immutable process settings loaded before application composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


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
    log_level: str
    enable_audit_logging: bool
    audit_log_file: Path
    mcp_transport: str
    mock_mode: bool
    insecure_skip_host_key_check: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        host = os.getenv("OPENWRT_HOST", "192.168.1.1").strip()
        user = os.getenv("OPENWRT_USER", "root").strip()
        if not host:
            raise ValueError("OPENWRT_HOST must not be empty")
        if not user:
            raise ValueError("OPENWRT_USER must not be empty")

        transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
        if transport != "stdio":
            raise ValueError("Only stdio is enabled in the hardened profile")

        mock_mode = _bool_env("OPENWRT_MOCK_MODE", False)
        insecure_host_key = _bool_env(
            "OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK",
            False,
        )
        known_hosts_raw = os.getenv("OPENWRT_KNOWN_HOSTS", "").strip()
        known_hosts = Path(known_hosts_raw) if known_hosts_raw else None
        ssh_key = Path(os.getenv("OPENWRT_SSH_KEY", "/app/keys/openwrt_id_ed25519"))
        password = os.getenv("OPENWRT_PASSWORD") or None
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(sorted(_LOG_LEVELS))}")

        if not mock_mode:
            if known_hosts is None and not insecure_host_key:
                raise ValueError(
                    "OPENWRT_KNOWN_HOSTS is required outside mock mode; "
                    "set OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK=1 only for an explicit "
                    "non-production exception"
                )
            if known_hosts is not None and not known_hosts.is_file():
                raise ValueError("OPENWRT_KNOWN_HOSTS must point to an existing regular file")
            if ssh_key.exists() and not ssh_key.is_file():
                raise ValueError("OPENWRT_SSH_KEY must point to a regular file")
            if not ssh_key.is_file() and password is None:
                raise ValueError(
                    "SSH authentication requires an existing OPENWRT_SSH_KEY file "
                    "or OPENWRT_PASSWORD"
                )

        return cls(
            openwrt_host=host,
            openwrt_port=_int_env("OPENWRT_PORT", 22, minimum=1, maximum=65535),
            openwrt_user=user,
            openwrt_ssh_key=ssh_key,
            openwrt_password=password,
            openwrt_known_hosts=known_hosts,
            insecure_skip_host_key_check=insecure_host_key,
            ssh_timeout=_int_env("SSH_TIMEOUT", 30, minimum=1, maximum=300),
            health_port=_int_env("HEALTH_PORT", 9094, minimum=1, maximum=65535),
            log_level=log_level,
            enable_audit_logging=_bool_env("ENABLE_AUDIT_LOGGING", True),
            audit_log_file=Path(os.getenv("AUDIT_LOG_FILE", "/app/log/openwrt_mcp.log")),
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
