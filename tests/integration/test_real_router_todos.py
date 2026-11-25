"""Owned placeholder for future capabilities outside the current L1 profile."""

from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.skip(
    reason=(
        "NOT_IMPLEMENTED(agent-with-isolated-openwrt-lab): write tools are inactive. "
        "After a reviewed principal-bound authorization + expiring approval subsystem "
        "exists, implement real plan/execute/verify/compensate acceptance here."
    )
)
def test_real_router_write_authorization_and_approval_workflow() -> None:
    raise NotImplementedError(
        "requires the future authenticated write profile and disposable OpenWRT lab"
    )
