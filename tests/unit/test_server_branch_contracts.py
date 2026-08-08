from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import openwrt_mcp.server as server_module
from openwrt_mcp.server import (
    HealthState,
    build_application,
    probe_dependency,
    run_readiness_probe_loop,
)
from openwrt_mcp.settings import Settings


class FakeMCP:
    def __init__(self, _: str, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class FakeSSH:
    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


class FakeExplorer:
    def __init__(self, *, success: bool = True) -> None:
        self.ssh = FakeSSH()
        self.success = success

    async def test_connection(self) -> dict[str, Any]:
        return {"success": self.success, "error": None if self.success else "unreachable"}

    def __getattr__(self, _: str) -> Any:
        async def operation(*args: Any) -> dict[str, Any]:
            return {"success": True, "args": list(args)}

        return operation


def settings(tmp_path: Path, *, mock_mode: bool = True) -> Settings:
    return Settings(
        openwrt_host="router.test",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=tmp_path / "key",
        openwrt_password="password",
        openwrt_known_hosts=tmp_path / "known_hosts",
        ssh_timeout=30,
        health_port=0,
        log_level="INFO",
        enable_audit_logging=False,
        audit_log_file=tmp_path / "audit.log",
        mcp_transport="stdio",
        mock_mode=mock_mode,
    )


def test_setup_logging_covers_initialization_repeat_and_insecure_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    previous_configured = root.__dict__.pop("_openwrt_configured", None)
    warnings: list[str] = []

    def record_warning(message: str, *args: Any) -> None:
        del args
        warnings.append(message)

    monkeypatch.setattr(server_module.logger, "warning", record_warning)
    try:
        cfg = replace(settings(tmp_path), insecure_skip_host_key_check=True)
        server_module.setup_logging(cfg)
        server_module.setup_logging(cfg)
        assert warnings == [
            "OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK is enabled; do not use this profile in production"
        ]
    finally:
        root.handlers.clear()
        root.handlers.extend(previous_handlers)
        root.setLevel(previous_level)
        if previous_configured is None:
            root.__dict__.pop("_openwrt_configured", None)
        else:
            root.__dict__["_openwrt_configured"] = previous_configured


def test_build_application_loads_settings_when_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = settings(tmp_path)
    monkeypatch.setattr(server_module, "load_settings", lambda: cfg)
    app = build_application(
        None,
        mcp_factory=FakeMCP,
        explorer_factory=FakeExplorer,
    )
    assert app.settings is cfg
    assert len(app.mcp.tools) == 19


def test_build_application_selects_default_mock_and_real_explorers(tmp_path: Path) -> None:
    mock_app = build_application(settings(tmp_path), mcp_factory=FakeMCP)
    assert type(mock_app.explorer).__name__ == "MockOpenWRTExplorer"

    real_app = build_application(settings(tmp_path, mock_mode=False), mcp_factory=FakeMCP)
    assert type(real_app.explorer).__name__ == "OpenWRTExplorer"


@pytest.mark.asyncio
async def test_official_lifespan_closes_explorer(tmp_path: Path) -> None:
    explorer = FakeExplorer()
    app = build_application(settings(tmp_path), explorer_factory=lambda: explorer)
    lifespan = app.mcp._lifespan
    async with lifespan(app.mcp):
        assert explorer.ssh.closed == 0
    assert explorer.ssh.closed == 1


@pytest.mark.asyncio
async def test_real_dependency_probe_covers_failure_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explorer = FakeExplorer(success=False)
    import openwrt_mcp.tools.explorer as explorer_module

    monkeypatch.setattr(explorer_module, "OpenWRTExplorer", lambda _: explorer)
    app = SimpleNamespace(settings=settings(tmp_path, mock_mode=False))
    state = HealthState(started_at=time.monotonic())
    await probe_dependency(app, state)
    snapshot = state.snapshot()
    assert snapshot["checked"] is True
    assert snapshot["ready"] is False
    assert snapshot["error"] == "unreachable"
    assert explorer.ssh.closed == 1


def test_readiness_loop_covers_zero_and_single_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = SimpleNamespace(settings=settings(tmp_path))
    state = HealthState(started_at=time.monotonic())
    already_stopped = threading.Event()
    already_stopped.set()
    run_readiness_probe_loop(app, state, already_stopped, interval_seconds=0)
    assert state.dependency_checked is False

    calls = 0

    async def fake_probe(_: Any, current: HealthState) -> None:
        nonlocal calls
        calls += 1
        current.update(healthy=True, error=None)
        stop.set()

    stop = threading.Event()
    monkeypatch.setattr(server_module, "probe_dependency", fake_probe)
    run_readiness_probe_loop(app, state, stop, interval_seconds=0)
    assert calls == 1
    assert state.snapshot()["ready"] is True
