from __future__ import annotations

import http.client
import json
import threading
import time
from dataclasses import replace

from openwrt_mcp.server import (
    HealthState,
    ReuseHTTPServer,
    build_application,
    make_health_handler,
    probe_dependency,
)


class FakeMCP:
    def __init__(self, _: str) -> None:
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


async def test_dependency_probe_sets_ready_state(settings) -> None:
    app = build_application(replace(settings, mock_mode=True), mcp_factory=FakeMCP)
    state = HealthState(started_at=time.monotonic())
    try:
        await probe_dependency(app, state)
        assert state.dependency_checked is True
        assert state.dependency_healthy is True
        assert state.dependency_error is None
    finally:
        await app.close()


def test_health_handler_distinguishes_live_ready_and_not_found(settings) -> None:
    app = build_application(replace(settings, mock_mode=True), mcp_factory=FakeMCP)
    state = HealthState(
        started_at=time.monotonic(), dependency_checked=True, dependency_healthy=True
    )
    server = ReuseHTTPServer(("127.0.0.1", 0), make_health_handler(app, state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        for path, expected in (("/live", 200), ("/ready", 200), ("/missing", 404)):
            connection.request("GET", path)
            response = connection.getresponse()
            body = json.loads(response.read()) if response.length != 0 else {}
            assert response.status == expected
            if path == "/ready":
                assert body["active_tools"] == 19
    finally:
        server.shutdown()
        server.server_close()

async def test_real_mode_probe_uses_temporary_explorer(settings, monkeypatch) -> None:
    from openwrt_mcp.tools import explorer as explorer_module

    events: list[str] = []

    class TemporarySSH:
        async def close(self) -> None:
            events.append("closed")

    class TemporaryExplorer:
        def __init__(self, _settings) -> None:
            self.ssh = TemporarySSH()

        async def test_connection(self):
            events.append("probed")
            return {"success": True}

    class ApplicationExplorer:
        def __init__(self) -> None:
            self.ssh = TemporarySSH()

        async def test_connection(self):
            raise AssertionError("application explorer must not be used by startup probe")

    monkeypatch.setattr(explorer_module, "OpenWRTExplorer", TemporaryExplorer)
    app = build_application(
        replace(settings, mock_mode=False),
        mcp_factory=FakeMCP,
        explorer_factory=ApplicationExplorer,
    )
    state = HealthState(started_at=time.monotonic())
    await probe_dependency(app, state)
    assert events == ["probed", "closed"]
    assert state.dependency_healthy is True
