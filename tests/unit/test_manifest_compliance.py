"""Unit tests: every tool manifest satisfies the Risk Consistency Matrix.

[L3+] The manifest fields are not independent. `risk`, `side_effects`,
`idempotent`, `retryable`, `reversible`, `requires_confirmation`, and `impact`
MUST form a consistent profile. This test asserts each registered tool
against the matrix from mcp-server-standards.md.
"""

from openwrt_mcp.tools.registration import register_openwrt_tools

# risk -> allowed values for each dependent field.
_MATRIX = {
    "READ": {
        "side_effects": {"none", "read"},
        "idempotent": {True},
        "retryable": {True},
        "reversible": {True},
        "requires_confirmation": {False},
        "impact": {"none"},
    },
    "WRITE": {
        "side_effects": {"write"},
        "idempotent": {True},
        "retryable": {True},
        "reversible": {True},
        "requires_confirmation": {True},
        "impact": {"transient", "persistent"},
    },
    "DESTRUCTIVE": {
        "side_effects": {"destructive"},
        "idempotent": {False},
        "retryable": {False},
        "reversible": {False},
        "requires_confirmation": {True},
        "impact": {"persistent", "service_outage"},
    },
}


def _manifests(mock_mcp):
    register_openwrt_tools(mock_mcp)
    out = {}
    for name, fn in mock_mcp._tools.items():
        manifest = getattr(fn, "__manifest__", None)
        assert manifest is not None, f"Tool '{name}' has no __manifest__"
        out[name] = manifest
    return out


class TestRiskConsistencyMatrix:
    """Each manifest's dependent fields must match its risk class."""

    def test_every_manifest_matches_matrix(self, mock_mcp):
        for name, manifest in _manifests(mock_mcp).items():
            risk = manifest["risk"]
            assert risk in _MATRIX, f"Tool '{name}' has unknown risk '{risk}'"
            for field, allowed in _MATRIX[risk].items():
                assert manifest[field] in allowed, (
                    f"Tool '{name}' ({risk}): {field}={manifest[field]!r} "
                    f"violates the Risk Consistency Matrix (allowed: {allowed})"
                )

    def test_non_read_tools_require_confirmation(self, mock_mcp):
        """Matrix rule 3: requires_confirmation MUST be true for every non-READ tool."""
        for name, manifest in _manifests(mock_mcp).items():
            if manifest["risk"] != "READ":
                assert manifest["requires_confirmation"] is True, (
                    f"Non-READ tool '{name}' must set requires_confirmation=true"
                )

    def test_reboot_device_is_destructive(self, mock_mcp):
        """Matrix rule 2: irreversible reboot MUST be DESTRUCTIVE, not WRITE."""
        manifest = _manifests(mock_mcp)["reboot_device"]
        assert manifest["risk"] == "DESTRUCTIVE"
        assert manifest["reversible"] is False
        assert manifest["retryable"] is False
