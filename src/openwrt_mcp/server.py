#!/usr/bin/env python3
"""
OpenWRT MCP Server
Model Context Protocol server for OpenWRT router management and diagnostics.

Architecture:
- Port 9094: Health check (lightweight HTTP server)
- Port 9095: MCP SSE transport (for LibreChat) - /sse, /messages
- Port 9096: REST API (Starlette) - /api/*
"""

import inspect
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from fastmcp import FastMCP

from openwrt_mcp.tools.constants import LOG_LEVEL, MCP_SSE_PORT, OPENWRT_SSH_KEY, REST_API_PORT
from openwrt_mcp.tools.registration import register_openwrt_tools

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("openwrt-mcp")

# =============================================================================
# HEALTH CHECK SERVER (port 9094)
# =============================================================================

HEALTH_STATE = {"status": "starting", "last_heartbeat": time.time()}
_health_lock = threading.Lock()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            with _health_lock:
                response = json.dumps(HEALTH_STATE).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


class ReuseHTTPServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR enabled for faster restarts."""

    allow_reuse_address = True


def start_health_server(port: int = 9094) -> HTTPServer:
    """Start lightweight HTTP server for health checks."""
    bind_host = _get_bind_host()
    server = ReuseHTTPServer((bind_host, port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True, name="HealthServer").start()
    logger.info("Health endpoint started on %s:%s", bind_host, port)
    return server


# =============================================================================
# BIND HOST
# =============================================================================


def _get_bind_host() -> str:
    """Return the host to bind to, defaulting to safe localhost."""
    if os.getenv("MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED") == "1":
        logger.critical("WARNING: MCP Server bound to 0.0.0.0 — PUBLIC ACCESS ENABLED")
        return "0.0.0.0"  # nosec B104 — deliberate: requires MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1
    logger.info("Binding to 127.0.0.1 (localhost only)")
    return "127.0.0.1"


# =============================================================================
# CONFIGURATION
# =============================================================================

if not os.path.exists(OPENWRT_SSH_KEY):
    logger.warning("SSH key not found at %s — OpenWRT features will be disabled", OPENWRT_SSH_KEY)

# =============================================================================
# INITIALIZE MCP SERVER
# =============================================================================

mcp = FastMCP("OpenWRT-Observer")

# =============================================================================
# REGISTER ALL TOOLS
# =============================================================================

register_openwrt_tools(mcp)


# =============================================================================
# TOOL HELPERS
# =============================================================================


def get_all_tools() -> dict[str, Any]:
    """Return a dictionary of all registered tools."""
    tools: dict[str, Any] = {}
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        tools = mcp._tool_manager._tools
    elif hasattr(mcp, "_tools"):
        tools = mcp._tools
    return tools


def get_tool(name: str) -> Any | None:
    """Return tool by name if available."""
    return get_all_tools().get(name)


def get_tool_manifest(tool_name: str) -> dict[str, Any] | None:
    """Return the manifest for a tool if available."""
    tool = get_tool(tool_name)
    if tool is not None and hasattr(tool, "__manifest__"):
        manifest: dict[str, Any] = tool.__manifest__
        return manifest
    return None


def get_tool_count() -> int:
    """Return the number of registered tools."""
    return len(get_all_tools())


tool_count = get_tool_count()


# =============================================================================
# REST API (Starlette on separate port 9096)
# =============================================================================


def create_rest_app() -> Any:
    """REST API for tools (alternative access, not MCP)."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    bind_host = _get_bind_host()

    async def health(request: Any) -> JSONResponse:
        from openwrt_mcp.observability import get_invocation_counts

        counts = get_invocation_counts()
        return JSONResponse(
            {
                "status": "healthy",
                "server": "OpenWRT-Observer",
                "version": "1.1.0",
                "tools_registered": get_tool_count(),
                "tool_invocations": counts,
                "total_invocations": sum(counts.values()),
                "endpoints": {
                    "mcp_sse": f"http://{bind_host}:{MCP_SSE_PORT}/sse",
                    "mcp_messages": f"http://{bind_host}:{MCP_SSE_PORT}/messages",
                    "rest_api": f"http://{bind_host}:{REST_API_PORT}/api/",
                },
            }
        )

    async def list_tools_endpoint(request: Any) -> JSONResponse:
        tools = get_all_tools()
        tool_list = []
        for name, tool in tools.items():
            desc = None
            if hasattr(tool, "description") and tool.description:
                desc = tool.description
            elif hasattr(tool, "fn") and hasattr(tool.fn, "__doc__") and tool.fn.__doc__:
                desc = tool.fn.__doc__.strip().split("\n")[0]
            tool_list.append({"name": name, "description": desc})
        return JSONResponse(
            {
                "success": True,
                "total": len(tool_list),
                "tools": sorted(tool_list, key=lambda x: x["name"]),
            }
        )

    async def call_tool_endpoint(request: Any) -> JSONResponse:
        tool_name = request.path_params.get("tool_name", "")

        try:
            body = await request.body()
            args = json.loads(body) if body else {}
        except json.JSONDecodeError:
            args = {}
        except Exception:
            args = {}

        tool = get_tool(tool_name)

        if tool is None:
            all_tool_names = list(get_all_tools().keys())
            return JSONResponse(
                {
                    "success": False,
                    "error": f"Tool '{tool_name}' not found",
                    "available_tools": sorted(all_tool_names)[:30],
                    "total_tools": len(all_tool_names),
                },
                status_code=404,
            )

        try:
            if hasattr(tool, "fn") and callable(tool.fn):
                fn = tool.fn
            elif callable(tool):
                fn = tool
            else:
                return JSONResponse(
                    {"success": False, "error": f"Tool '{tool_name}' is not callable"},
                    status_code=500,
                )

            if inspect.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                result = fn(**args)

            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    pass

            return JSONResponse({"success": True, "tool": tool_name, "result": result})

        except TypeError as e:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"Invalid arguments: {e}",
                    "tool": tool_name,
                },
                status_code=400,
            )
        except Exception as e:
            return JSONResponse(
                {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "tool": tool_name,
                },
                status_code=500,
            )

    async def tool_manifest_endpoint(request: Any) -> JSONResponse:
        tool_name = request.path_params.get("tool_name", "")
        manifest = get_tool_manifest(tool_name)
        if manifest is None:
            return JSONResponse(
                {"success": False, "error": f"Manifest not found for tool '{tool_name}'"},
                status_code=404,
            )
        return JSONResponse({"success": True, "manifest": manifest})

    routes = [
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/api/health", endpoint=health, methods=["GET"]),
        Route("/api/tools", endpoint=list_tools_endpoint, methods=["GET"]),
        Route("/api/tools/{tool_name}", endpoint=call_tool_endpoint, methods=["POST"]),
        Route("/api/tools/{tool_name}/manifest", endpoint=tool_manifest_endpoint, methods=["GET"]),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    return Starlette(routes=routes, middleware=middleware)


def run_rest_api() -> None:
    """Start REST API in a separate thread."""
    import uvicorn

    app = create_rest_app()
    bind_host = _get_bind_host()
    logger.info("REST API started on %s:%s", bind_host, REST_API_PORT)
    uvicorn.run(app, host=bind_host, port=REST_API_PORT, log_level="warning")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> None:
    """Main entry point for the OpenWRT MCP server."""
    from openwrt_mcp.tools.constants import OPENWRT_HOST, OPENWRT_PORT

    # 1. Start health check server (port 9094)
    start_health_server(port=9094)
    with _health_lock:
        HEALTH_STATE["status"] = "healthy"
        HEALTH_STATE["last_heartbeat"] = time.time()

    logger.info("OpenWRT-Observer MCP Server starting")
    logger.info("OpenWRT Host: %s:%s", OPENWRT_HOST, OPENWRT_PORT)
    logger.info("Registered tools: %s", tool_count)

    # 2. Start REST API in a separate thread (port 9096)
    bind_host = _get_bind_host()
    rest_thread = threading.Thread(target=run_rest_api, daemon=True, name="RestAPI")
    rest_thread.start()

    logger.info("Endpoints:")
    logger.info("  Health:      http://%s:9094/health", bind_host)
    logger.info("  MCP SSE:     http://%s:%s/sse", bind_host, MCP_SSE_PORT)
    logger.info("  MCP MSG:     http://%s:%s/messages", bind_host, MCP_SSE_PORT)
    logger.info("  REST API:    http://%s:%s/api/", bind_host, REST_API_PORT)

    # 3. Start MCP SSE server (port 9095) - BLOCKING!
    logger.info("Starting MCP SSE transport on port %s...", MCP_SSE_PORT)
    mcp_host = _get_bind_host()
    mcp.run(transport="sse", host=mcp_host, port=MCP_SSE_PORT)


if __name__ == "__main__":
    main()
