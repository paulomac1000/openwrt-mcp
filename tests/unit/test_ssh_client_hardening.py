from __future__ import annotations

import asyncio
import os
import sys
import types
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.ssh_client import _MAX_CAPTURE_BYTES, SSHConnection


class ConnectionLost(Exception):
    pass


class DisconnectError(Exception):
    pass


class FakeReader:
    def __init__(self, payload: bytes = b"", *, delay: float = 0) -> None:
        self._payload = payload
        self._offset = 0
        self._delay = delay

    async def read(self, size: int) -> bytes:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._offset >= len(self._payload):
            return b""
        end = min(self._offset + size, len(self._payload))
        chunk = self._payload[self._offset : end]
        self._offset = end
        return chunk


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"ok",
        stderr: bytes = b"",
        exit_status: int = 0,
        delay: float = 0,
        on_wait_closed: Any | None = None,
    ) -> None:
        self.stdout = FakeReader(stdout, delay=delay)
        self.stderr = FakeReader(stderr, delay=delay)
        self.exit_status = exit_status
        self.closed = False
        self._waited = False
        self._on_wait_closed = on_wait_closed

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        if not self._waited:
            self._waited = True
            if self._on_wait_closed is not None:
                self._on_wait_closed()


class FakeConnection:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.fail = False
        self.closed = False
        self.processes: list[FakeProcess] = []
        self.process_created = asyncio.Event()
        self.stdout = b"ok"
        self.stderr = b""
        self.delay = 0.01

    def is_closed(self) -> bool:
        return self.closed

    async def create_process(self, command: str, **kwargs: Any) -> FakeProcess:
        assert kwargs["encoding"] is None
        self.calls += 1
        if self.fail:
            raise ConnectionLost("link dropped with secret=password123")
        self.active += 1
        self.max_active = max(self.max_active, self.active)

        def finished() -> None:
            self.active -= 1

        process = FakeProcess(
            stdout=self.stdout,
            stderr=self.stderr,
            delay=self.delay,
            on_wait_closed=finished,
        )
        self.processes.append(process)
        self.process_created.set()
        return process

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def install_asyncssh(
    monkeypatch: pytest.MonkeyPatch,
    connections: FakeConnection | list[FakeConnection],
) -> None:
    pool = [connections] if isinstance(connections, FakeConnection) else list(connections)
    connect_calls = 0

    async def connect(**_: Any) -> FakeConnection:
        nonlocal connect_calls
        if connect_calls >= len(pool):
            raise AssertionError("unexpected extra SSH connection")
        connection = pool[connect_calls]
        connect_calls += 1
        return connection

    module = types.SimpleNamespace(
        ConnectionLost=ConnectionLost,
        DisconnectError=DisconnectError,
        connect=connect,
    )
    monkeypatch.setitem(sys.modules, "asyncssh", module)


async def test_non_concurrent_safe_ssh_calls_are_serialized(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    await asyncio.gather(
        client.execute("ubus call system board"),
        client.execute("ubus call system info"),
    )
    assert connection.max_active == 1
    assert connection.calls == 2


async def test_timeout_override_is_task_local(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    observed: list[tuple[str, int]] = []

    async def bounded(command: str, *, deadline_seconds: int) -> tuple[str, str, int]:
        observed.append((command, deadline_seconds))
        return "ok", "", 0

    monkeypatch.setattr(client, "_run_bounded", bounded)

    async def invoke(timeout_seconds: int, command: str) -> None:
        with client.timeout_scope(timeout_seconds):
            await client.execute(command)

    await asyncio.gather(
        invoke(5, "ubus call system board"),
        invoke(17, "ubus call system info"),
    )
    assert sorted(timeout for _, timeout in observed) == [5, 17]


async def test_output_capture_is_bounded_before_decode_and_discards_session(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    connection.delay = 0
    connection.stdout = b"x" * (_MAX_CAPTURE_BYTES // 2 + 1)
    connection.stderr = b"y" * (_MAX_CAPTURE_BYTES // 2 + 1)
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)

    stdout, error, code = await client.execute("ubus call system board")

    assert stdout == ""
    assert code == 126
    assert str(_MAX_CAPTURE_BYTES) in error
    assert client._connection is None  # noqa: SLF001
    assert connection.closed is True
    assert all(process.closed for process in connection.processes)


async def test_cancellation_discards_session_and_next_call_reconnects(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakeConnection()
    first.delay = 60
    second = FakeConnection()
    second.delay = 0
    install_asyncssh(monkeypatch, [first, second])
    client = SSHConnection(settings)

    task = asyncio.create_task(client.execute("ubus call system board"))
    await first.process_created.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert first.closed is True
    assert first.processes[0].closed is True
    assert client._connection is None  # noqa: SLF001

    stdout, error, code = await client.execute("ubus call system info")
    assert (stdout, error, code) == ("ok", "", 0)
    assert second.calls == 1


async def test_timeout_discards_process_and_session(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    connection.delay = 2
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)

    stdout, error, code = await client.execute(
        "ubus call system board",
        timeout_seconds=1,
    )

    assert (stdout, error, code) == ("", "Timeout after 1s", 124)
    assert connection.closed is True
    assert connection.processes[0].closed is True
    assert client._connection is None  # noqa: SLF001


async def test_closed_cached_connection_is_replaced_before_dispatch(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = FakeConnection()
    stale.closed = True
    fresh = FakeConnection()
    fresh.delay = 0
    install_asyncssh(monkeypatch, fresh)
    client = SSHConnection(settings)
    client._connection = stale  # noqa: SLF001

    stdout, error, code = await client.execute("ubus call system board")

    assert (stdout, error, code) == ("ok", "", 0)
    assert stale.calls == 0
    assert fresh.calls == 1


async def test_write_connection_loss_is_not_retried(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    connection.fail = True
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    _, error, code = await client.execute_write("uci commit network")
    assert code == 125
    assert "AMBIGUOUS_OUTCOME" in error
    assert "password123" not in error
    assert connection.calls == 1
    assert connection.closed is True


async def test_read_connection_loss_is_not_replayed(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    connection.fail = True
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    _, error, code = await client.execute("ubus call system board")
    assert code == 125
    assert "was not replayed" in error
    assert "password123" not in error
    assert connection.calls == 1
    assert connection.closed is True


async def test_write_requires_known_hosts(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(replace(settings, openwrt_known_hosts=None))
    _, error, code = await client.execute_write("uci commit network")
    assert code == 1
    assert "OPENWRT_KNOWN_HOSTS" in error
    assert connection.calls == 0


async def test_audit_log_redacts_secret_and_ip_and_is_private(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    connection.delay = 0
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    await client.execute_write("uci set wireless.radio0.key=192.0.2.123")
    path = Path(settings.audit_log_file)
    audit = await asyncio.to_thread(path.read_text, encoding="utf-8")
    assert "192.0.2.123" not in audit
    assert "<REDACTED>" in audit
    stat_result = await asyncio.to_thread(path.stat)
    assert stat_result.st_mode & 0o777 == 0o600


async def test_audit_log_refuses_symlink_target(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW unavailable on this POSIX host")
    connection = FakeConnection()
    connection.delay = 0
    install_asyncssh(monkeypatch, connection)
    target = tmp_path / "target.log"
    target.write_text("sentinel\n", encoding="utf-8")
    symlink = tmp_path / "audit.log"
    symlink.symlink_to(target)
    client = SSHConnection(replace(settings, audit_log_file=symlink))

    stdout, error, code = await client.execute("ubus call system board")

    assert (stdout, error, code) == ("ok", "", 0)
    assert target.read_text(encoding="utf-8") == "sentinel\n"


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
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    command: Any,
) -> None:
    connection = FakeConnection()
    install_asyncssh(monkeypatch, connection)
    client = SSHConnection(settings)
    _, error, code = await client.execute(command)  # type: ignore[arg-type]
    assert code == 1
    assert error.startswith("Security denial:")
    assert connection.calls == 0
