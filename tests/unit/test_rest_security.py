from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from starlette.testclient import TestClient

from openwrt_mcp.server import Application, create_rest_app
from openwrt_mcp.tools.registration import build_invocation_kernel


class FakeSSH:
    def timeout_scope(self, seconds: int) -> Any:
        class Scope:
            def __enter__(self) -> None:
                return None

            def __exit__(self, *args: Any) -> None:
                return None

        return Scope()

    async def close(self) -> None:
        return None


class FakeExplorer:
    def __init__(self) -> None:
        self.ssh = FakeSSH()

    async def get_system_info(self) -> dict[str, Any]:
        return {"success": True, "hostname": "mock-router"}

    def __getattr__(self, _: str) -> Any:
        async def generic(*args: Any) -> dict[str, Any]:
            return {"success": True, "args": list(args)}

        return generic


class FakeMCP:
    pass


def app_for(settings: Any) -> Application:
    explorer = FakeExplorer()
    return Application(
        settings=settings,
        mcp=FakeMCP(),
        kernel=build_invocation_kernel(settings, explorer),
        explorer=explorer,
    )


def secured(settings: Any, **overrides: Any) -> Any:
    return replace(settings, rest_auth_token="secret", **overrides)


def auth_headers(token: str = "secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_rest_app_cannot_be_constructed_without_token(settings: Any) -> None:
    with pytest.raises(ValueError, match="MCP_REST_AUTH_TOKEN"):
        create_rest_app(app_for(settings))


def test_rest_requires_bearer_and_uses_constant_time_comparison(settings: Any) -> None:
    client = TestClient(create_rest_app(app_for(secured(settings))))
    assert client.get("/api/tools").status_code == 401
    assert client.get(
        "/api/tools",
        headers=auth_headers("wrong"),
    ).status_code == 401
    response = client.get("/api/tools", headers=auth_headers())
    assert response.status_code == 200


def test_rest_rejects_oversized_body_before_invocation(settings: Any) -> None:
    bounded = secured(settings, max_request_body_bytes=1024)
    client = TestClient(create_rest_app(app_for(bounded)))
    response = client.post(
        "/api/tools/get_router_info",
        content=b"{" + b'"x":"' + b"a" * 2000 + b'"}',
        headers={
            **auth_headers(),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PARAM"


def test_invalid_json_is_not_silently_coerced(settings: Any) -> None:
    client = TestClient(create_rest_app(app_for(secured(settings))))
    response = client.post(
        "/api/tools/get_router_info",
        content=b"{not-json}",
        headers={
            **auth_headers(),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


def test_rest_delegates_to_kernel(settings: Any) -> None:
    client = TestClient(create_rest_app(app_for(secured(settings))))
    response = client.post(
        "/api/tools/get_router_info",
        json={},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["data"]["hostname"] == "mock-router"
