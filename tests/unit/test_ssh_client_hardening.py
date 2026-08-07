from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.ssh_client import SSHConnection


class ConnectionLost(Exception):
    pass


class DisconnectError(Exception):
    pass


class FakeResult:
    stdout = "ok"
    stderr = ""
    exit_status = 0


class FakeConnection:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.timeouts: list[int] = []
        self.calls = 0
        self.fail_write = False
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def run(self, command: str, timeout: int) -> FakeResult:
        self.calls += 1
        self.timeouts.append(timeout)
        if self.fail_write:
            raise ConnectionLost("link dropped")
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return FakeResult()

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def install_asyncssh(monkeypatch: pytest.MonkeyPatch, connection: FakeConnection) -> None:
    module = types.SimpleNamespace(
        ConnectionLost=ConnectionLost,
        DisconnectError=DisconnectError,
        connect=lambda **_: connection,
    )

    async def connect(**_: Any) -> FakeConnection:
        return connection

    module.connect = connect
    monkeypatch.setitem(sys.modules, "asyncssh", module)


async def test_non_concurrent_safe_ssh_calls_are_serialized(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    await asyncio.gather(
        client.execute("ubus call system board"),
        client.execute("ubus call system info"),
    )
    assert connection.max_active == 1


async def test_timeout_override_is_task_local(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)

    async def invoke(timeout: int, command: str) -> None:
        with client.timeout_scope(timeout):
            await client.execute(command)

    await asyncio.gather(
        invoke(5, "ubus call system board"),
        invoke(17, "ubus call system info"),
    )
    assert sorted(connection.timeouts) == [5, 17]


async def test_write_connection_loss_is_not_retried(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = FakeConnection()
    connection.fail_write = True
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    _, error, code = await client.execute_write("uci commit network")
    assert code == 125
    assert "AMBIGUOUS_OUTCOME" in error
    assert connection.calls == 1


async def test_read_connection_loss_is_not_replayed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = FakeConnection()
    connection.fail_write = True
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    _, error, code = await client.execute("ubus call system board")
    assert code == 125
    assert "was not replayed" in error
    assert connection.calls == 1


async def test_write_requires_known_hosts(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(replace(settings, openwrt_known_hosts=None))
    _, error, code = await client.execute_write("uci commit network")
    assert code == 1
    assert "OPENWRT_KNOWN_HOSTS" in error
    assert connection.calls == 0


async def test_audit_log_redacts_secret_and_ip(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    await client.execute_write("uci set wireless.radio0.key=192.0.2.123")
    audit = Path(settings.audit_log_file).read_text(encoding="utf-8")
    assert "192.0.2.123" not in audit
    assert "<REDACTED>" in audit


@pytest.mark.parametrize(
    "command",
    [
        "ubus\u00a0list",
        "ubus\u2003list",
        "ubus\u2028list",
        "ping -c 1 example.com\uff1breboot",
        b"ubus list",
    ],
)
async def test_rejected_read_input_never_dispatches(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, command: Any
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    _, error, code = await client.execute(command)  # type: ignore[arg-type]
    assert code == 1
    assert error.startswith("Security denial:")
    assert connection.calls == 0
