#!/usr/bin/env python3
"""Composition root for the hardened OpenWRT MCP profile."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from openwrt_mcp import __version__
from openwrt_mcp.application import InvocationKernel, decode_kernel_response
from openwrt_mcp.observability import get_invocation_counts
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
    """Construct dependencies after settings validation without network I/O."""
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
            ready = self.dependency_checked and self.dependency_healthy and fresh
            return {
                "ready": ready,
                "checked": self.dependency_checked,
                "healthy": self.dependency_healthy,
                "checked_at_monotonic": checked_at,
                "error": self.dependency_error,
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
                ready = bool(dependency.pop("ready"))
                self._json(
                    200 if ready else 503,
                    {
                        "status": "ready" if ready else "not_ready",
                        "version": __version__,
                        "uptime_seconds": int(
                            time.monotonic() - state.started_at
                        ),
                        "dependency": {
                            "name": "openwrt-ssh",
                            **dependency,
                        },
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
    """Probe readiness without binding the application SSH client to this loop."""
    owns_probe = not app.settings.mock_mode
    if owns_probe:
        from openwrt_mcp.tools.explorer import OpenWRTExplorer

        explorer = OpenWRTExplorer(app.settings)
    else:
        explorer = app.explorer

    try:
        result = await explorer.test_connection()
    except Exception:
        result = {"success": False, "error": "dependency probe failed"}
    finally:
        if owns_probe:
            await explorer.ssh.close()
    healthy = bool(result.get("success"))
    state.update(
        healthy=healthy,
        error=None if healthy else str(result.get("error")),
    )


def start_readiness_probe(
    app: Application,
    state: HealthState,
    *,
    interval_seconds: int = _READINESS_PROBE_INTERVAL_SECONDS,
) -> tuple[threading.Thread, threading.Event]:
    """Refresh readiness with bounded, short-lived dependency probes."""
    stop = threading.Event()

    def run() -> None:
        while not stop.wait(interval_seconds):
            try:
                asyncio.run(probe_dependency(app, state))
            except Exception:
                logger.exception("Readiness probe loop failed")

    thread = threading.Thread(
        target=run,
        daemon=True,
        name="ReadinessProbe",
    )
    thread.start()
    return thread, stop


def _authorized(request: Any, settings: Settings) -> bool:
    token = settings.rest_auth_token
    if token is None:
        return False
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {token}"
    return secrets.compare_digest(supplied, expected)


async def _bounded_json_body(request: Any, limit: int) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length > limit:
            raise ValueError("request body exceeds configured limit")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ValueError("request body exceeds configured limit")
        chunks.append(chunk)
    if not chunks:
        return {}
    decoded = json.loads(b"".join(chunks))
    if not isinstance(decoded, dict):
        raise ValueError("request body must be a JSON object")
    return decoded


def create_rest_app(app: Application) -> Any:
    if not app.settings.rest_auth_token:
        raise ValueError("REST requires MCP_REST_AUTH_TOKEN")

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(_: Any) -> JSONResponse:
        return JSONResponse(
            {
                "status": "alive",
                "version": __version__,
                "active_tools": len(app.kernel.registry.active()),
                "supported_tools": len(app.kernel.registry.supported()),
                "tool_invocations": get_invocation_counts(),
            }
        )

    async def list_tools(request: Any) -> JSONResponse:
        if not _authorized(request, app.settings):
            return JSONResponse(
                {
                    "success": False,
                    "error": {"code": "AUTHENTICATION_REQUIRED"},
                },
                status_code=401,
            )
        return JSONResponse(
            {
                "success": True,
                "supported": app.kernel.registry.supported(),
                "active": app.kernel.registry.active(),
            }
        )

    async def call_tool(request: Any) -> JSONResponse:
        if not _authorized(request, app.settings):
            return JSONResponse(
                {
                    "success": False,
                    "error": {"code": "AUTHENTICATION_REQUIRED"},
                },
                status_code=401,
            )
        try:
            arguments = await _bounded_json_body(
                request,
                app.settings.max_request_body_bytes,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return JSONResponse(
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_PARAM",
                        "message": sanitize_log_line(str(exc)),
                        "retryable": False,
                    },
                },
                status_code=400,
            )
        payload = await app.kernel.invoke(
            request.path_params["tool_name"],
            arguments,
        )
        status, parsed = decode_kernel_response(payload)
        return JSONResponse(parsed, status_code=status)

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/health", health, methods=["GET"]),
        Route("/api/tools", list_tools, methods=["GET"]),
        Route("/api/tools/{tool_name}", call_tool, methods=["POST"]),
    ]
    middleware: list[Middleware] = []
    if app.settings.allowed_origins:
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(app.settings.allowed_origins),
                allow_methods=["GET", "POST"],
                allow_headers=["Authorization", "Content-Type"],
            )
        )
    return Starlette(routes=routes, middleware=middleware)


def run_rest_api(app: Application) -> None:
    import uvicorn

    uvicorn.run(
        create_rest_app(app),
        host=_LOOPBACK_HOST,
        port=app.settings.rest_api_port,
        log_level="warning",
    )


def main() -> None:
    settings = load_settings()
    app = build_application(settings)
    state = HealthState(started_at=time.monotonic())
    health_server = start_health_server(app, state)
    readiness_stop: threading.Event | None = None

    if settings.enable_rest_api:
        threading.Thread(
            target=run_rest_api,
            args=(app,),
            daemon=True,
            name="RestAPI",
        ).start()

    try:
        asyncio.run(probe_dependency(app, state))
        _, readiness_stop = start_readiness_probe(app, state)
        logger.info(
            "Starting stdio MCP transport with %d active capabilities",
            len(app.kernel.registry.active()),
        )
        app.mcp.run(transport="stdio")
    finally:
        if readiness_stop is not None:
            readiness_stop.set()
        health_server.shutdown()


if __name__ == "__main__":
    main()
