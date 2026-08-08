from __future__ import annotations

import asyncio
import os
import stat
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.observability import CallerContext, request_context
from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.ssh_client import SSHConnection


class ConnectionLost(Exception):
    pass


class DisconnectError(Exception):
    pass


class Result:
    stdout = "ok"
    stderr = ""
    exit_status = 0


class FakeConnection:
    def __init__(self, behavior: str = "ok") -> None:
        self.behavior = behavior
        self.closed = False
        self.waited = False
        self.calls = 0
        self.entered = asyncio.Event()

    def is_closed(self) -> bool:
        return self.closed

    async def run(self, command: str, **kwargs: Any) -> Result:
        del command
        assert isinstance(kwargs.get("timeout"), int)
        self.calls += 1
        self.entered.set()
        if self.behavior == "timeout":
            raise TimeoutError
        if self.behavior == "lost":
            raise ConnectionLost("secret endpoint 192.0.2.7")
        if self.behavior == "error":
            raise RuntimeError("password=super-secret")
        if self.behavior == "slow":
            await asyncio.sleep(60)
        return Result()

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited = True


class Connector:
    def __init__(self, *connections: FakeConnection) -> None:
        self.connections = list(connections)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> FakeConnection:
        self.calls.append(kwargs)
        return self.connections.pop(0)


def install_asyncssh(monkeypatch: pytest.MonkeyPatch, connector: Connector) -> None:
    module = types.SimpleNamespace(
        ConnectionLost=ConnectionLost,
        DisconnectError=DisconnectError,
        connect=connector,
    )
    monkeypatch.setitem(sys.modules, "asyncssh", module)


def settings(tmp_path: Path) -> Settings:
    key = tmp_path / "id_ed25519"
    known = tmp_path / "known_hosts"
    key.write_text("key", encoding="utf-8")
    known.write_text("host key", encoding="utf-8")
    return Settings(
        openwrt_host="router.test",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=key,
        openwrt_password=None,
        openwrt_known_hosts=known,
        ssh_timeout=30,
        health_port=19094,
        log_level="INFO",
        enable_audit_logging=True,
        audit_log_file=tmp_path / "audit.log",
        mcp_transport="stdio",
        mock_mode=False,
    )


@pytest.mark.asyncio
async def test_explicit_zero_timeout_is_rejected_without_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = Connector(FakeConnection())
    install_asyncssh(monkeypatch, connector)
    client = SSHConnection(settings(tmp_path))
    assert await client.execute("ubus call system board", timeout_seconds=0) == (
        "",
        "Invalid timeout",
        1,
    )
    assert connector.calls == []


@pytest.mark.asyncio
async def test_timeout_discards_session_and_followup_reconnects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = FakeConnection("timeout")
    second = FakeConnection()
    connector = Connector(first, second)
    install_asyncssh(monkeypatch, connector)
    client = SSHConnection(settings(tmp_path))

    _, error, code = await client.execute("ubus call system board", timeout_seconds=1)
    assert (code, error) == (124, "Timeout after 1s")
    assert first.closed and first.waited
    assert client._connection is None

    stdout, _, code = await client.execute("ubus call system board")
    assert (stdout, code) == ("ok", 0)
    assert len(connector.calls) == 2


@pytest.mark.asyncio
async def test_task_cancellation_discards_session_and_re_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = FakeConnection("slow")
    second = FakeConnection()
    connector = Connector(first, second)
    install_asyncssh(monkeypatch, connector)
    client = SSHConnection(settings(tmp_path))

    task = asyncio.create_task(client.execute("ubus call system board"))
    await first.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first.closed and first.waited
    assert client._connection is None

    assert (await client.execute("ubus call system board"))[2] == 0
    assert len(connector.calls) == 2


@pytest.mark.asyncio
async def test_connection_loss_is_generic_not_replayed_and_session_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = FakeConnection("lost")
    connector = Connector(first)
    install_asyncssh(monkeypatch, connector)
    client = SSHConnection(settings(tmp_path))
    _, error, code = await client.execute("ubus call system board")
    assert code == 125
    assert error == "SSH connection lost during read; command was not replayed"
    assert "192.0.2.7" not in error
    assert first.calls == 1
    assert first.closed and first.waited


@pytest.mark.asyncio
async def test_unexpected_upstream_error_is_not_exposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = FakeConnection("error")
    connector = Connector(first)
    install_asyncssh(monkeypatch, connector)
    client = SSHConnection(settings(tmp_path))
    _, error, code = await client.execute("ubus call system board")
    assert code == 1
    assert error == "SSH command execution failed"
    assert "super-secret" not in error


@pytest.mark.asyncio
async def test_closed_cached_connection_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = FakeConnection()
    stale.closed = True
    replacement = FakeConnection()
    connector = Connector(replacement)
    install_asyncssh(monkeypatch, connector)
    client = SSHConnection(settings(tmp_path))
    client._connection = stale
    assert await client.connect() is True
    assert client._connection is replacement


def test_audit_log_is_private_and_redacts_network_identifiers(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    client = SSHConnection(cfg)
    with request_context("req", caller=CallerContext("os-uid:4242")):
        client._log_audit("ping -c 1 192.0.2.9 # aa:bb:cc:dd:ee:ff auth_token=abc")
    rendered = cfg.audit_log_file.read_text(encoding="utf-8")
    assert "192.0.2.9" not in rendered
    assert "aa:bb:cc:dd:ee:ff" not in rendered
    assert "abc" not in rendered
    assert stat.S_IMODE(cfg.audit_log_file.stat().st_mode) == 0o600


def test_audit_log_refuses_symlink_target_when_supported(tmp_path: Path) -> None:
    if not getattr(os, "O_NOFOLLOW", 0):
        pytest.skip("O_NOFOLLOW unavailable")
    target = tmp_path / "target.log"
    target.write_text("sentinel", encoding="utf-8")
    link = tmp_path / "audit.log"
    link.symlink_to(target)
    cfg = settings(tmp_path)
    object.__setattr__(cfg, "audit_log_file", link)
    SSHConnection(cfg)._log_audit("ubus call system board")
    assert target.read_text(encoding="utf-8") == "sentinel"
