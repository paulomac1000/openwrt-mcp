"""Owned placeholders for tests requiring an isolated OpenWRT laboratory."""

from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.skip(
    reason=(
        "TODO(agent-with-isolated-openwrt-lab): verify SSH host-key mismatch fails "
        "before command execution on a disposable router."
    )
)
def test_real_router_host_identity_enrollment() -> None:
    pass


@pytest.mark.integration
@pytest.mark.skip(
    reason=(
        "TODO(agent-with-isolated-openwrt-lab): cancel a controlled slow read and "
        "prove bounded SSH, lock, and connection cleanup."
    )
)
def test_real_router_cancellation_cleanup() -> None:
    pass


@pytest.mark.integration
@pytest.mark.skip(
    reason=(
        "TODO(agent-with-isolated-openwrt-lab): after reviewed approval and authorization "
        "implementation, test plan/execute/verify/compensate for one write workflow."
    )
)
def test_real_router_write_workflow() -> None:
    pass
