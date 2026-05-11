"""Observability: request IDs, per-tool counters, and audit support."""

import threading
import time
import uuid
from collections import defaultdict
from typing import Any

_request_counter: dict[str, int] = defaultdict(int)
_counter_lock = threading.Lock()
TOOLS_VERSION = "1.1.0"


def generate_request_id() -> str:
    """Generate a unique request ID (UUID4)."""
    return str(uuid.uuid4())


def record_invocation(tool_name: str) -> None:
    """Record a tool invocation for per-tool metrics."""
    with _counter_lock:
        _request_counter[tool_name] += 1


def get_invocation_counts() -> dict[str, int]:
    """Return per-tool invocation counts."""
    with _counter_lock:
        return dict(_request_counter)


def build_meta(
    tool_name: str,
    start_time: float,
    cached: bool = False,
    retry_safe: bool = True,
) -> dict[str, Any]:
    """Build the _meta envelope for a response.

    Args:
        tool_name: Name of the tool being invoked.
        start_time: time.monotonic() value at the start of execution.
        cached: Whether the result was served from cache.
        retry_safe: Whether the operation is safe to retry.

    Returns:
        Dict with request_id, duration_ms, tool_version, cached, retry_safe.
    """
    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    record_invocation(tool_name)
    return {
        "request_id": generate_request_id(),
        "duration_ms": elapsed_ms,
        "tool_version": TOOLS_VERSION,
        "cached": cached,
        "retry_safe": retry_safe,
    }
