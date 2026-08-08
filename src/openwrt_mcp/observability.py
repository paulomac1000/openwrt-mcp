"""Request context and bounded in-process metrics."""

from __future__ import annotations

import contextvars
import os
import secrets
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from openwrt_mcp import __version__

TOOLS_VERSION = __version__


@dataclass(frozen=True, slots=True)
class CallerContext:
    """Immutable identity derived from the local process/OS trust boundary."""

    principal: str
    boundary: str = "local-process"


@lru_cache(maxsize=1)
def process_caller_context() -> CallerContext:
    """Resolve the L1 caller from the OS process identity, never router identity."""

    get_euid = getattr(os, "geteuid", None)
    if callable(get_euid):
        principal = f"os-uid:{get_euid()}"
    else:  # pragma: no cover - non-POSIX fallback
        principal = f"process-user:{os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'}"
    return CallerContext(principal=principal)


_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_caller_context: contextvars.ContextVar[CallerContext | None] = contextvars.ContextVar(
    "caller_context", default=None
)
_request_counter: dict[str, int] = defaultdict(int)
_counter_lock = threading.Lock()


def generate_request_id() -> str:
    return secrets.token_hex(16)


def set_request_id(request_id: str) -> contextvars.Token[str]:
    return _request_id.set(request_id)


def reset_request_id(token: contextvars.Token[str]) -> None:
    _request_id.reset(token)


def get_request_id() -> str:
    return _request_id.get()


def get_caller_context() -> CallerContext:
    return _caller_context.get() or CallerContext("system:internal", boundary="internal")


@contextmanager
def request_context(
    request_id: str | None = None,
    *,
    caller: CallerContext | None = None,
) -> Iterator[str]:
    resolved = request_id or generate_request_id()
    request_token = set_request_id(resolved)
    caller_token = _caller_context.set(caller or process_caller_context())
    try:
        yield resolved
    finally:
        _caller_context.reset(caller_token)
        reset_request_id(request_token)


def record_invocation(tool_name: str) -> None:
    with _counter_lock:
        _request_counter[tool_name] += 1


def get_invocation_counts() -> dict[str, int]:
    with _counter_lock:
        return dict(_request_counter)


def build_meta(
    tool_name: str,
    start_time: float,
    *,
    cached: bool = False,
    retry_safe: bool = False,
) -> dict[str, Any]:
    record_invocation(tool_name)
    caller = get_caller_context()
    return {
        "request_id": get_request_id(),
        "caller": {"principal": caller.principal, "boundary": caller.boundary},
        "duration_ms": int((time.monotonic() - start_time) * 1000),
        "tool_version": TOOLS_VERSION,
        "cached": cached,
        "retry_safe": retry_safe,
    }
