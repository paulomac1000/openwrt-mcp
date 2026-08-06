from __future__ import annotations

import asyncio

from openwrt_mcp.observability import get_request_id, request_context


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
