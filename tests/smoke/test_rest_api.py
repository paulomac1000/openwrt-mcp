"""Smoke tests for the OpenWRT-MCP REST API.

These tests make real HTTP calls to a running server.
They are skipped when the server is not running.
"""

import os
import socket

import pytest
import requests

REST_PORT = int(os.getenv("REST_API_PORT", "9096"))
BASE_URL = f"http://127.0.0.1:{REST_PORT}"


def _server_running():
    try:
        s = socket.create_connection(("127.0.0.1", REST_PORT), timeout=1)
        s.close()
        return True
    except TimeoutError, ConnectionRefusedError, OSError:
        return False


pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not _server_running(), reason="MCP server not running"),
]


class TestHealthEndpoint:
    """Verify health endpoint returns correct structure."""

    def test_health_returns_200(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "tools_registered" in data
        assert data["tools_registered"] == 24

    def test_health_includes_version(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        data = r.json()
        assert "version" in data

    def test_health_includes_invocation_counts(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        data = r.json()
        assert "tool_invocations" in data
        assert isinstance(data["tool_invocations"], dict)


class TestToolsEndpoint:
    """Verify tools list endpoint returns all 24 tools."""

    def test_list_tools_returns_all(self):
        r = requests.get(f"{BASE_URL}/api/tools", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["total"] == 24
        assert len(data["tools"]) == 24

    def test_every_tool_has_risk_prefix(self):
        r = requests.get(f"{BASE_URL}/api/tools", timeout=5)
        data = r.json()
        for tool in data["tools"]:
            desc = tool.get("description")
            assert desc is not None, f"Tool '{tool['name']}' has no description"
            is_ok = (
                desc.startswith("[READ]")
                or desc.startswith("[WRITE]")
                or desc.startswith("[DESTRUCTIVE]")
            )
            assert is_ok, f"Tool '{tool['name']}' description missing risk prefix: {desc[:30]}"

    def test_unknown_tool_returns_404(self):
        r = requests.post(
            f"{BASE_URL}/api/tools/nonexistent_tool",
            json={},
            timeout=5,
        )
        assert r.status_code == 404
        data = r.json()
        assert data["success"] is False
        assert "available_tools" in data


class TestManifestEndpoint:
    """Verify manifest endpoint works correctly."""

    def test_get_router_info_manifest(self):
        r = requests.get(
            f"{BASE_URL}/api/tools/get_router_info/manifest",
            timeout=5,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        manifest = data["manifest"]
        assert manifest["name"] == "get_router_info"
        assert manifest["risk"] == "READ"
        assert manifest["version"] is not None

    def test_unknown_tool_manifest_404(self):
        r = requests.get(
            f"{BASE_URL}/api/tools/nonexistent/manifest",
            timeout=5,
        )
        assert r.status_code == 404
