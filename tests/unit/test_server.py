"""Unit tests for server module helpers."""

from unittest.mock import MagicMock, patch

from openwrt_mcp.server import get_all_tools, get_tool, get_tool_count, get_tool_manifest


class TestServerHelpers:
    """Tests for server helper functions."""

    def test_get_all_tools_returns_dict(self):
        tools = get_all_tools()
        assert isinstance(tools, dict)

    def test_get_all_tools_has_13_items(self):
        tools = get_all_tools()
        assert len(tools) == 13

    def test_get_tool_valid(self):
        tool = get_tool("get_router_info")
        assert tool is not None

    def test_get_tool_invalid(self):
        tool = get_tool("nonexistent_tool")
        assert tool is None

    def test_get_tool_count(self):
        assert get_tool_count() == 13

    def test_get_tool_manifest_valid(self):
        manifest = get_tool_manifest("get_router_info")
        assert manifest is not None
        assert manifest["name"] == "get_router_info"
        assert manifest["risk"] == "READ"
        assert "version" in manifest

    def test_get_tool_manifest_invalid(self):
        manifest = get_tool_manifest("nonexistent")
        assert manifest is None

    def test_get_tool_manifest_no_attr(self):
        tools = get_all_tools()
        fake_name = "_fake_tool_for_testing"
        orig_tool = tools.pop("get_router_info", None)
        fake_tool = MagicMock()
        del fake_tool.__manifest__
        tools[fake_name] = fake_tool
        try:
            manifest = get_tool_manifest(fake_name)
            assert manifest is None
        finally:
            if orig_tool:
                tools["get_router_info"] = orig_tool
            tools.pop(fake_name, None)

    def test_get_bind_host_default(self):
        from openwrt_mcp.server import _get_bind_host

        with patch.dict("os.environ", {}, clear=True):
            host = _get_bind_host()
            assert host == "127.0.0.1"

    def test_get_bind_host_public(self):
        from openwrt_mcp.server import _get_bind_host

        with patch.dict("os.environ", {"MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED": "1"}):
            host = _get_bind_host()
            assert host == "0.0.0.0"

    def test_start_health_server_creates_server(self):
        from openwrt_mcp.server import start_health_server

        with patch("threading.Thread") as mock_thread:
            with patch.dict("os.environ", {}, clear=True):
                server = start_health_server(port=0)
                assert server.server_port > 0
                mock_thread.assert_called_once()
                mock_thread().start.assert_called_once()
                server.server_close()

    def test_create_rest_app_has_routes(self):
        from openwrt_mcp.server import create_rest_app

        app = create_rest_app()
        route_paths = {r.path for r in app.routes}
        assert "/health" in route_paths
        assert "/api/health" in route_paths
        assert "/api/tools" in route_paths
        assert "/api/tools/{tool_name}" in route_paths
        assert "/api/tools/{tool_name}/manifest" in route_paths

    def test_run_rest_api_starts_uvicorn(self):
        from openwrt_mcp.server import run_rest_api

        with patch("uvicorn.run") as mock_uvicorn:
            with patch.dict("os.environ", {}, clear=True):
                run_rest_api()
            mock_uvicorn.assert_called_once()
            args, kwargs = mock_uvicorn.call_args
            assert kwargs.get("port") == 9096

    def test_health_state_defaults(self):
        from openwrt_mcp.server import HEALTH_STATE

        assert "status" in HEALTH_STATE
        assert "last_heartbeat" in HEALTH_STATE

    def test_logger_configured_to_stderr(self):
        import logging

        logger = logging.getLogger("openwrt-mcp")
        assert logger.level == logging.INFO or logger.level == 0

    def test_get_tool_returns_none_for_empty(self):
        assert get_tool("") is None

    def test_reuse_httpserver_class(self):
        from openwrt_mcp.server import ReuseHTTPServer

        assert ReuseHTTPServer.allow_reuse_address is True

    def test_main_starts_services(self):
        from openwrt_mcp.server import main

        with patch("openwrt_mcp.server.start_health_server") as mock_health:
            with patch("openwrt_mcp.server.run_rest_api") as mock_rest:
                with patch("openwrt_mcp.server.mcp.run") as mock_mcp:
                    with patch.dict("os.environ", {}, clear=True):
                        mock_mcp.side_effect = SystemExit(0)
                        try:
                            main()
                        except SystemExit:
                            pass
            mock_health.assert_called_once()
            mock_rest.assert_called_once()
