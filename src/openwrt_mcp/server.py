#!/usr/bin/env python3
"""Composition root for the hardened OpenWRT MCP stdio profile."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from openwrt_mcp import __version__
from openwrt_mcp.application import InvocationKernel
from openwrt_mcp.sanitizer import sanitize_log_line
from openwrt_mcp.settings import Settings, load_settings

logger = logging.getLogger("openwrt-mcp")
_LOOPBACK_HOST = "127.0.0.1"
_READINESS_TTL_SECONDS = 60
_READINESS_PROBE_INTERVAL_SECONDS = 30


class SanitizingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return sanitize_log_line(super().format(record))


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger()
    if getattr(root, "_openwrt_configured", False):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        SanitizingFormatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
    )
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))
    setattr(root, "_openwrt_configured", True)
    if settings.insecure_skip_host_key_check:
        logger.warning(
            "OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK is enabled; "
            "do not use this profile in production"
        )


@dataclass(slots=True)
class Application:
    settings: Settings
    mcp: Any
    kernel: InvocationKernel
    explorer: Any

    async def close(self) -> None:
        await self.explorer.ssh.close()


def build_application(
    settings: Settings | None = None,
    *,
    mcp_factory: Callable[..., Any] | None = None,
    explorer_factory: Callable[[], Any] | None = None,
) -> Application:
    """Construct dependencies after validation without network I/O."""
    resolved = settings or load_settings()
    setup_logging(resolved)
    use_official_lifespan = mcp_factory is None
    if mcp_factory is None:
        from mcp.server import MCPServer

        mcp_factory = MCPServer
    if explorer_factory is None:
        if resolved.mock_mode:
            from openwrt_mcp.mock_explorer import MockOpenWRTExplorer

            explorer_factory = MockOpenWRTExplorer
        else:
            from openwrt_mcp.tools.explorer import OpenWRTExplorer

            explorer_factory = lambda: OpenWRTExplorer(resolved)

    from openwrt_mcp.tools.registration import (
        build_invocation_kernel,
        register_openwrt_tools,
    )

    explorer = explorer_factory()
    kernel = build_invocation_kernel(resolved, explorer)

    if use_official_lifespan:

        @asynccontextmanager
        async def lifespan(_: Any) -> AsyncIterator[None]:
            try:
                yield None
            finally:
                await explorer.ssh.close()

        mcp = mcp_factory("OpenWRT-Observer", lifespan=lifespan)
    else:
        mcp = mcp_factory("OpenWRT-Observer")
    register_openwrt_tools(mcp, kernel)
    return Application(resolved, mcp, kernel, explorer)


@dataclass(slots=True)
class HealthState:
    started_at: float
    dependency_checked: bool = False
    dependency_healthy: bool = False
    dependency_error: str | None = None
    dependency_checked_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, *, healthy: bool, error: str | None) -> None:
        with self._lock:
            self.dependency_checked = True
            self.dependency_healthy = healthy
            self.dependency_error = error
            self.dependency_checked_at = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            checked_at = self.dependency_checked_at
            fresh = (
                checked_at is not None
                and time.monotonic() - checked_at <= _READINESS_TTL_SECONDS
            )
            return {
                "checked": self.dependency_checked,
                "healthy": self.dependency_healthy,
                "ready": self.dependency_checked
                and self.dependency_healthy
                and fresh,
                "fresh": fresh,
                "error": self.dependency_error,
                "checked_at_monotonic": checked_at,
            }


class ReuseHTTPServer(HTTPServer):
    allow_reuse_address = True


def make_health_handler(
    app: Application,
    state: HealthState,
) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/live":
                self._json(200, {"status": "alive", "version": __version__})
                return
            if self.path in {"/health", "/ready"}:
                dependency = state.snapshot()
                ready = bool(dependency["ready"])
                self._json(
                    200 if ready else 503,
                    {
                        "status": "ready" if ready else "not_ready",
                        "version": __version__,
                        "uptime_seconds": int(
                            time.monotonic() - state.started_at
                        ),
                        "dependency": dependency,
                        "active_tools": len(app.kernel.registry.active()),
                        "supported_tools": len(app.kernel.registry.supported()),
                    },
                )
                return
            self._json(404, {"error": "not found"})

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return HealthHandler


def start_health_server(app: Application, state: HealthState) -> HTTPServer:
    server = ReuseHTTPServer(
        (_LOOPBACK_HOST, app.settings.health_port),
        make_health_handler(app, state),
    )
    threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="HealthServer",
    ).start()
    return server


async def probe_dependency(app: Application, state: HealthState) -> None:
    """Probe with a new explorer owned by the probe event loop."""
    if app.settings.mock_mode:
        from openwrt_mcp.mock_explorer import MockOpenWRTExplorer

        explorer: Any = MockOpenWRTExplorer()
    else:
        from openwrt_mcp.tools.explorer import OpenWRTExplorer

        explorer = OpenWRTExplorer(app.settings)
    try:
        result = await explorer.test_connection()
        healthy = bool(result.get("success"))
        state.update(
            healthy=healthy,
            error=None if healthy else str(result.get("error")),
        )
    except Exception:
        state.update(healthy=False, error="dependency probe failed")
    finally:
        await explorer.ssh.close()


def run_readiness_probe_loop(
    app: Application,
    state: HealthState,
    stop_event: threading.Event,
    *,
    interval_seconds: float = _READINESS_PROBE_INTERVAL_SECONDS,
) -> None:
    """Own a private loop and private SSH clients for readiness probes."""
    while not stop_event.is_set():
        asyncio.run(probe_dependency(app, state))
        stop_event.wait(interval_seconds)


def main() -> None:
    settings = load_settings()
    app = build_application(settings)
    state = HealthState(started_at=time.monotonic())
    health_server = start_health_server(app, state)
    stop_event = threading.Event()
    probe_thread = threading.Thread(
        target=run_readiness_probe_loop,
        args=(app, state, stop_event),
        daemon=True,
        name="ReadinessProbe",
    )
    probe_thread.start()

    try:
        logger.info(
            "Starting stdio MCP transport with %d active capabilities",
            len(app.kernel.registry.active()),
        )
        app.mcp.run(transport="stdio")
    finally:
        stop_event.set()
        probe_thread.join(timeout=2)
        health_server.shutdown()
        health_server.server_close()


if __name__ == "__main__":
    main()
