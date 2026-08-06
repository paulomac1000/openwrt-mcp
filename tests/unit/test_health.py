from __future__ import annotations

import http.client
import json
import threading
import time
from dataclasses import replace
from typing import Any

from openwrt_mcp.server import (
    HealthState,
    ReuseHTTPServer,
    build_application,
    make_health_handler,
    probe_dependency,
)


class FakeMCP:
    def __init__(self, _: str) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[fn.__name__] = fn
            return fn

        return decorator


async def test_dependency_probe_sets_ready_state(settings: Any) -> None:
    app = build_application(
        replace(settings, mock_mode=True),
        mcp_factory=FakeMCP,
    )
    state = HealthState(started_at=time.monotonic())
    try:
        await probe_dependency(app, state)
        snapshot = state.snapshot()
        assert snapshot["checked"] is True
        assert snapshot["healthy"] is True
        assert snapshot["ready"] is True
        assert snapshot["error"] is None
    finally:
        await app.close()


def test_stale_dependency_probe_is_not_ready(monkeypatch: Any) -> None:
    state = HealthState(started_at=0)
    state.update(healthy=True, error=None)
    checked = state.dependency_checked_at
    assert checked is not None
    monkeypatch.setattr(time, "monotonic", lambda: checked + 61)
    assert state.snapshot()["ready"] is False


def test_health_handler_distinguishes_live_ready_and_not_found(
    settings: Any,
) -> None:
    app = build_application(
        replace(settings, mock_mode=True),
        mcp_factory=FakeMCP,
    )
    state = HealthState(started_at=time.monotonic())
    state.update(healthy=True, error=None)
    server = ReuseHTTPServer(
        ("127.0.0.1", 0),
        make_health_handler(app, state),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.server_port,
            timeout=2,
        )
        for path, expected in (
            ("/live", 200),
            ("/ready", 200),
            ("/missing", 404),
        ):
            connection.request("GET", path)
            response = connection.getresponse()
            body = json.loads(response.read()) if response.length != 0 else {}
            assert response.status == expected
            if path == "/ready":
                assert body["active_tools"] == 19
    finally:
        server.shutdown()
        server.server_close()


async def test_real_mode_probe_uses_temporary_explorer(
    settings: Any,
    monkeypatch: Any,
) -> None:
    from openwrt_mcp.tools import explorer as explorer_module

    events: list[str] = []

    class TemporarySSH:
        async def close(self) -> None:
            events.append("closed")

    class TemporaryExplorer:
        def __init__(self, _settings: Any) -> None:
            self.ssh = TemporarySSH()

        async def test_connection(self) -> dict[str, Any]:
            events.append("probed")
            return {"success": True}

    class ApplicationExplorer:
        def __init__(self) -> None:
            self.ssh = TemporarySSH()

        async def test_connection(self) -> dict[str, Any]:
            raise AssertionError(
                "application explorer must not be used by startup probe"
            )

    monkeypatch.setattr(explorer_module, "OpenWRTExplorer", TemporaryExplorer)
    app = build_application(
        replace(settings, mock_mode=False),
        mcp_factory=FakeMCP,
        explorer_factory=ApplicationExplorer,
    )
    state = HealthState(started_at=time.monotonic())
    await probe_dependency(app, state)
    assert events == ["probed", "closed"]
    assert state.snapshot()["healthy"] is True
