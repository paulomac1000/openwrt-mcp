"""Unit tests for the observability module."""

import time

from openwrt_mcp.observability import (
    TOOLS_VERSION,
    build_meta,
    generate_request_id,
    get_invocation_counts,
    record_invocation,
)


class TestObservability:
    """Tests for request IDs, counters, and _meta envelopes."""

    def test_generate_request_id_is_uuid4_format(self):
        rid = generate_request_id()
        parts = rid.split("-")
        assert len(parts) == 5
        assert len(rid) == 36

    def test_request_ids_are_unique(self):
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100

    def test_record_and_get_counts(self):
        record_invocation("get_router_info")
        record_invocation("get_router_info")
        record_invocation("get_router_wifi_status")
        counts = get_invocation_counts()
        assert counts["get_router_info"] >= 2
        assert counts["get_router_wifi_status"] >= 1

    def test_build_meta_has_all_fields(self):
        meta = build_meta("test_tool", time.monotonic())
        assert "request_id" in meta
        assert "duration_ms" in meta
        assert isinstance(meta["duration_ms"], int)
        assert meta["tool_version"] == TOOLS_VERSION
        assert "cached" in meta
        assert "retry_safe" in meta

    def test_build_meta_records_invocation(self):
        counts_before = get_invocation_counts().get("specific_tool_test", 0)
        build_meta("specific_tool_test", time.monotonic())
        counts_after = get_invocation_counts().get("specific_tool_test", 0)
        assert counts_after == counts_before + 1
