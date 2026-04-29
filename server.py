#!/usr/bin/env python3
"""
OpenWRT MCP Server
Model Context Protocol server for OpenWRT router management and diagnostics.

Architecture:
- Port 9094: Health check (lightweight HTTP server)
- Port 9095: MCP SSE transport (for LibreChat) - /sse, /messages
- Port 9096: REST API (Starlette) - /api/*
"""

import os
import sys
import json
import time
import threading
import inspect
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional

from fastmcp import FastMCP

# =============================================================================
# HEALTH CHECK SERVER (port 9094)
# =============================================================================

HEALTH_STATE = {"status": "starting", "last_heartbeat": time.time()}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(HEALTH_STATE).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server(port=9094):
    """Start lightweight HTTP server for health checks."""
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True, name="HealthServer").start()
    print(f"[health] HTTP health endpoint started on port {port}")
    return server


# =============================================================================
# CONFIGURATION
# =============================================================================

OPENWRT_HOST = os.getenv("OPENWRT_HOST", "192.168.0.200")
OPENWRT_PORT = int(os.getenv("OPENWRT_PORT", "22"))
OPENWRT_USER = os.getenv("OPENWRT_USER", "root")
OPENWRT_SSH_KEY = os.getenv("OPENWRT_SSH_KEY", "/app/keys/openwrt_id_ed25519")

# PORTS
MCP_SSE_PORT = int(os.getenv("MCP_SSE_PORT", "9095"))
REST_API_PORT = int(os.getenv("REST_API_PORT", "9096"))

if not os.path.exists(OPENWRT_SSH_KEY):
    print(f"[server] WARNING: SSH key not found at {OPENWRT_SSH_KEY} - OpenWRT features will be disabled", file=sys.stderr)

# =============================================================================
# INITIALIZE MCP SERVER
# =============================================================================

mcp = FastMCP("OpenWRT-Observer")

# =============================================================================
# REGISTER ALL TOOLS
# =============================================================================

from tools.openwrt_explorer import register_openwrt_tools
register_openwrt_tools(mcp)


# =============================================================================
# TOOL HELPERS
# =============================================================================

def get_all_tools() -> Dict[str, Any]:
    """Return a dictionary of all registered tools."""
    if hasattr(mcp, '_tool_manager') and hasattr(mcp._tool_manager, '_tools'):
        return mcp._tool_manager._tools
    elif hasattr(mcp, '_tools'):
        return mcp._tools
    return {}


def get_tool(name: str) -> Optional[Any]:
    """Return tool by name if available."""
    return get_all_tools().get(name)


def get_tool_count() -> int:
    """Return the number of registered tools."""
    return len(get_all_tools())


tool_count = get_tool_count()


# =============================================================================
# REST API (Starlette on separate port 9096)
# =============================================================================

def create_rest_app():
    """REST API for tools (alternative access, not MCP)."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    
    async def health(request):
        return JSONResponse({
            "status": "healthy",
            "server": "OpenWRT-Observer",
            "version": "1.0.0",
            "tools_registered": get_tool_count(),
            "endpoints": {
                "mcp_sse": f"http://0.0.0.0:{MCP_SSE_PORT}/sse",
                "mcp_messages": f"http://0.0.0.0:{MCP_SSE_PORT}/messages",
                "rest_api": f"http://0.0.0.0:{REST_API_PORT}/api/",
            }
        })
    
    async def list_tools_endpoint(request):
        tools = get_all_tools()
        tool_list = []
        for name, tool in tools.items():
            desc = None
            if hasattr(tool, 'description') and tool.description:
                desc = tool.description
            elif hasattr(tool, 'fn') and hasattr(tool.fn, '__doc__') and tool.fn.__doc__:
                desc = tool.fn.__doc__.strip().split('\n')[0]
            tool_list.append({"name": name, "description": desc})
        return JSONResponse({
            "success": True,
            "total": len(tool_list),
            "tools": sorted(tool_list, key=lambda x: x["name"])
        })
    
    async def call_tool_endpoint(request):
        tool_name = request.path_params.get('tool_name', '')
        
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
                    "total_tools": len(all_tool_names)
                },
                status_code=404
            )
        
        try:
            if hasattr(tool, 'fn') and callable(tool.fn):
                fn = tool.fn
            elif callable(tool):
                fn = tool
            else:
                return JSONResponse(
                    {"success": False, "error": f"Tool '{tool_name}' is not callable"},
                    status_code=500
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
                {"success": False, "error": f"Invalid arguments: {e}", "tool": tool_name},
                status_code=400
            )
        except Exception as e:
            import traceback
            return JSONResponse(
                {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "tool": tool_name,
                },
                status_code=500
            )
    
    routes = [
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/api/health", endpoint=health, methods=["GET"]),
        Route("/api/tools", endpoint=list_tools_endpoint, methods=["GET"]),
        Route("/api/tools/{tool_name}", endpoint=call_tool_endpoint, methods=["POST"]),
    ]
    
    middleware = [
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    ]
    
    return Starlette(routes=routes, middleware=middleware)


def run_rest_api():
    """Start REST API in a separate thread."""
    import uvicorn
    app = create_rest_app()
    print(f"[rest] REST API started on port {REST_API_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=REST_API_PORT, log_level="warning")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # 1. Start health check server (port 9094)
    start_health_server(port=9094)
    HEALTH_STATE["status"] = "healthy"
    HEALTH_STATE["last_heartbeat"] = time.time()
    
    print(f"[server] " + "=" * 50)
    print(f"[server] OpenWRT-Observer MCP Server")
    print(f"[server] " + "=" * 50)
    print(f"[server] OpenWRT Host: {OPENWRT_HOST}:{OPENWRT_PORT}")
    print(f"[server] Registered tools: {tool_count}")
    print(f"[server] " + "-" * 50)
    
    # 2. Start REST API in a separate thread (port 9096)
    rest_thread = threading.Thread(target=run_rest_api, daemon=True, name="RestAPI")
    rest_thread.start()
    
    print(f"[server] Endpoints:")
    print(f"[server]   Health:      http://0.0.0.0:9094/health")
    print(f"[server]   MCP SSE:     http://0.0.0.0:{MCP_SSE_PORT}/sse")
    print(f"[server]   MCP MSG:     http://0.0.0.0:{MCP_SSE_PORT}/messages")
    print(f"[server]   REST API:    http://0.0.0.0:{REST_API_PORT}/api/")
    print(f"[server] " + "=" * 50)
    
    # 3. Start MCP SSE server (port 9095) - BLOCKING!
    print(f"[server] Starting MCP SSE transport on port {MCP_SSE_PORT}...")
    mcp.run(transport="sse", host="0.0.0.0", port=MCP_SSE_PORT)
