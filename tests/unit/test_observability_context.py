from __future__ import annotations

import asyncio
import json
import os
import time

import pytest

from openwrt_mcp.observability import (
    CallerContext,
    build_meta,
    get_caller_context,
    get_request_id,
    process_caller_context,
    request_context,
)


def test_request_context_resets_after_scope() -> None:
    assert get_request_id() == "-"
    with request_context("abc"):
        assert get_request_id() == "abc"
    assert get_request_id() == "-"


async def test_request_ids_do_not_cross_concurrent_tasks() -> None:
    seen: dict[str, list[str]] = {"a": [], "b": []}

    async def worker(name: str) -> None:
        with request_context(name):
            seen[name].append(get_request_id())
            await asyncio.sleep(0)
            seen[name].append(get_request_id())

    await asyncio.gather(worker("a"), worker("b"))
    assert seen == {"a": ["a", "a"], "b": ["b", "b"]}


async def test_caller_context_does_not_cross_concurrent_tasks() -> None:
    seen: dict[str, list[str]] = {"a": [], "b": []}

    async def worker(name: str) -> None:
        with request_context(name, caller=CallerContext(f"test:{name}")):
            seen[name].append(get_caller_context().principal)
            await asyncio.sleep(0)
            seen[name].append(get_caller_context().principal)

    await asyncio.gather(worker("a"), worker("b"))
    assert seen == {"a": ["test:a", "test:a"], "b": ["test:b", "test:b"]}


def test_model_meta_does_not_expose_raw_caller_principal() -> None:
    with request_context("abc", caller=CallerContext("os-uid:1234")):
        meta = build_meta("test_tool", time.monotonic())

    assert meta["caller_boundary"] == "local-process"
    assert "caller" not in meta
    assert "os-uid:1234" not in json.dumps(meta, sort_keys=True)


def test_process_caller_context_uses_posix_effective_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_caller_context.cache_clear()
    monkeypatch.setattr(os, "geteuid", lambda: 4242)
    try:
        caller = process_caller_context()
        assert caller.principal == "os-uid:4242"
        assert caller.boundary == "local-process"
    finally:
        process_caller_context.cache_clear()


def test_process_caller_context_fails_closed_without_posix_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_caller_context.cache_clear()
    monkeypatch.delattr(os, "geteuid", raising=False)
    try:
        with pytest.raises(RuntimeError, match="POSIX host"):
            process_caller_context()
    finally:
        process_caller_context.cache_clear()
