from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.explorer import OpenWRTExplorer
from openwrt_mcp.tools.registration import build_invocation_kernel


class RecordingSSH:
    def __init__(self) -> None:
        self.commands: list[str] = []

    @contextmanager
    def timeout_scope(self, seconds: int) -> Iterator[None]:
        assert 1 <= seconds <= 300
        yield

    async def execute(self, command: str) -> tuple[str, str, int]:
        self.commands.append(command)
        return "", "", 0


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        openwrt_host="mock",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=tmp_path / "key",
        openwrt_password=None,
        openwrt_known_hosts=tmp_path / "known_hosts",
        insecure_skip_host_key_check=False,
        ssh_timeout=30,
        health_port=9094,
        log_level="INFO",
        enable_audit_logging=False,
        audit_log_file=tmp_path / "audit.log",
        mcp_transport="stdio",
        mock_mode=True,
    )


ADVERSARIAL = [
    "example.com;id",
    "example.com&&id",
    "example.com|id",
    "example.com`id`",
    "example.com$(id)",
    "example.com>out",
    "example.com\\id",
    "example.com\nid",
    "example.com\rid",
    "example.com\x00id",
    "example.com\u00a0id",
    "example.com\u2003id",
    "example.com\u2028id",
    'example.com"id',
    "example.com'id",
]


@pytest.mark.parametrize(
    ("capability", "field"),
    [
        ("read_router_uci_config", "config_name"),
        ("ping_host", "host"),
        ("traceroute_host", "host"),
        ("nslookup_host", "host"),
        ("nslookup_host", "dns_server"),
        ("wifi_scan", "radio"),
    ],
)
@pytest.mark.parametrize("bad_value", ADVERSARIAL)
async def test_rejected_shell_bound_input_never_dispatches(
    tmp_path: Path,
    capability: str,
    field: str,
    bad_value: str,
) -> None:
    ssh = RecordingSSH()
    explorer = OpenWRTExplorer(_settings(tmp_path), ssh=ssh)  # type: ignore[arg-type]
    kernel = build_invocation_kernel(_settings(tmp_path), explorer)
    arguments: dict[str, Any] = {}
    if capability == "nslookup_host":
        arguments = {"host": "example.com", "dns_server": "8.8.8.8"}
    arguments[field] = bad_value

    result = await kernel.invoke(capability, arguments)

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "INVALID_PARAM"
    assert ssh.commands == []
