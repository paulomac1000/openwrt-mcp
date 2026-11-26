from openwrt_mcp import __version__


def test_maintenance_release_version_is_2_0_1() -> None:
    assert __version__ == "2.0.1"
