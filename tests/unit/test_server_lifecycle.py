from __future__ import annotations

import http.client
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import openwrt_mcp.server as server_module
from openwrt_mcp.server import (
    HealthState,
    build_application,
    probe_dependency,
    start_health_server,
)
from openwrt_mcp.settings import Settings


class FakeMCP:
    def __init__(self, _: str, **__: Any) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class FakeSSH:
    async def close(self) -> None:
        return None


class FakeExplorer:
    def __init__(self) -> None:
        self.ssh = FakeSSH()

    async def test_connection(self) -> dict[str, Any]:
        return {"success": True}

    def __getattr__(self, _: str) -> Any:
        async def operation(*args: Any) -> dict[str, Any]:
            return {"success": True, "args": list(args)}

        return operation


def settings(tmp_path: Path) -> Settings:
    return Settings(
        openwrt_host="mock",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=tmp_path / "key",
        openwrt_password=None,
        openwrt_known_hosts=None,
        ssh_timeout=30,
        health_port=0,
        log_level="INFO",
        enable_audit_logging=False,
        audit_log_file=tmp_path / "audit.log",
        mcp_transport="stdio",
        mock_mode=True,
    )


def test_health_state_starts_unready_and_records_failure() -> None:
    state = HealthState(started_at=time.monotonic())
    initial = state.snapshot()
    assert initial["checked"] is False
    assert initial["ready"] is False
    state.update(healthy=False, error="dependency failed")
    failed = state.snapshot()
    assert failed["checked"] is True
    assert failed["healthy"] is False
    assert failed["ready"] is False
    assert failed["error"] == "dependency failed"


def test_start_health_server_serves_live_and_not_found(tmp_path: Path) -> None:
    app = build_application(
        settings(tmp_path),
        mcp_factory=FakeMCP,
        explorer_factory=FakeExplorer,
    )
    state = HealthState(started_at=time.monotonic())
    health = start_health_server(app, state)
    try:
        client = http.client.HTTPConnection("127.0.0.1", health.server_port, timeout=2)
        client.request("GET", "/live")
        response = client.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["status"] == "alive"

        client.request("GET", "/missing")
        response = client.getresponse()
        assert response.status == 404
        assert json.loads(response.read()) == {"error": "not found"}
    finally:
        health.shutdown()
        health.server_close()


@pytest.mark.asyncio
async def test_probe_dependency_sanitizes_unexpected_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = build_application(
        settings(tmp_path),
        mcp_factory=FakeMCP,
        explorer_factory=FakeExplorer,
    )
    state = HealthState(started_at=time.monotonic())

    class BrokenExplorer:
        def __init__(self) -> None:
            self.ssh = FakeSSH()

        async def test_connection(self) -> dict[str, Any]:
            raise RuntimeError("password=should-never-surface")

    import openwrt_mcp.mock_explorer as mock_module

    monkeypatch.setattr(mock_module, "MockOpenWRTExplorer", BrokenExplorer)
    await probe_dependency(app, state)
    snapshot = state.snapshot()
    assert snapshot["ready"] is False
    assert snapshot["error"] == "dependency probe failed"
    assert "should-never-surface" not in str(snapshot)


def test_main_always_stops_auxiliary_services(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = settings(tmp_path)
    calls: list[str] = []

    class MCP:
        def run(self, *, transport: str) -> None:
            assert transport == "stdio"
            calls.append("mcp-run")
            raise RuntimeError("stop test")

    app = SimpleNamespace(
        settings=cfg,
        mcp=MCP(),
        kernel=SimpleNamespace(registry=SimpleNamespace(active=lambda: [1])),
    )

    class Health:
        def shutdown(self) -> None:
            calls.append("health-shutdown")

        def server_close(self) -> None:
            calls.append("health-close")

    class Thread:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def start(self) -> None:
            calls.append("thread-start")

        def join(self, timeout: float) -> None:
            assert timeout == 2
            calls.append("thread-join")

    monkeypatch.setattr(server_module, "load_settings", lambda: cfg)
    monkeypatch.setattr(server_module, "build_application", lambda _: app)
    monkeypatch.setattr(server_module, "start_health_server", lambda *_: Health())
    monkeypatch.setattr(server_module.threading, "Thread", Thread)

    with pytest.raises(RuntimeError, match="stop test"):
        server_module.main()
    assert calls == [
        "thread-start",
        "mcp-run",
        "thread-join",
        "health-shutdown",
        "health-close",
    ]
