from __future__ import annotations

import pytest

from openwrt_mcp import artifact_smoke


def test_explicit_server_argv_is_preserved_for_container_smoke() -> None:
    argv = [
        "docker",
        "run",
        "--rm",
        "--init",
        "-i",
        "--network",
        "none",
        "-e",
        "OPENWRT_MOCK_MODE=1",
        "openwrt-mcp:ci-test",
    ]

    params = artifact_smoke._server_params(argv)

    assert params.command == "docker"
    assert params.args == argv[1:]
    assert params.env["OPENWRT_MOCK_MODE"] == "1"
    assert params.env["HEALTH_ENABLED"] == "0"


def test_default_server_argv_uses_installed_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifact_smoke.shutil, "which", lambda _: "/venv/bin/openwrt-mcp")

    params = artifact_smoke._server_params()

    assert params.command == "/venv/bin/openwrt-mcp"
    assert params.args == []


def test_explicit_command_separator_is_removed() -> None:
    assert artifact_smoke._command_argv(["--", "docker", "run", "image"]) == [
        "docker",
        "run",
        "image",
    ]
    assert artifact_smoke._command_argv([]) == []
