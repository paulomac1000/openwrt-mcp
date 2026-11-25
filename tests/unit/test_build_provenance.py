import json
from pathlib import Path

import pytest

from openwrt_mcp import __version__
from openwrt_mcp.settings import Settings


def test_provenance_comes_from_installed_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENWRT_MOCK_MODE", "1")
    monkeypatch.setenv("OPENWRT_BUILD_REVISION", "b" * 40)
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    assert Settings.from_env().provenance.revision == "unknown"
    receipt = tmp_path / "share/openwrt-mcp/provenance.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"revision": "a" * 40, "wheel_sha256": "1" * 64, "version": __version__}),
        encoding="utf-8",
    )
    provenance = Settings.from_env().provenance
    assert provenance.revision == "a" * 40
    assert provenance.wheel_sha256 == "1" * 64


def test_conflicting_runtime_version_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENWRT_MOCK_MODE", "1")
    monkeypatch.setattr("sys.prefix", str(tmp_path))
    receipt = tmp_path / "share/openwrt-mcp/provenance.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"revision": "a" * 40, "wheel_sha256": "1" * 64, "version": "1.3.0"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="provenance"):
        Settings.from_env()
