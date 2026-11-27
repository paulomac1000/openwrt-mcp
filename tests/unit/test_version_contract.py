from openwrt_mcp import __version__


def test_release_integrity_version_is_2_0_2() -> None:
    assert __version__ == "2.0.2"
