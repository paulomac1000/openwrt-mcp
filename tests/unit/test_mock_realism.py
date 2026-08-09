"""Mock router data must mirror real OpenWRT output shapes and stay internally consistent."""

from __future__ import annotations

import pytest

from openwrt_mcp.mock_explorer import MockOpenWRTExplorer


@pytest.fixture
def mock_explorer() -> MockOpenWRTExplorer:
    return MockOpenWRTExplorer()


@pytest.mark.asyncio
async def test_mock_uci_sample_uses_real_key_value_shape(
    mock_explorer: MockOpenWRTExplorer,
) -> None:
    result = await mock_explorer.read_uci_config("network")
    assert result["success"] is True
    assert result["entries_count"] == len(result["sample"]) > 0
    for key, value in result["sample"].items():
        assert key.startswith("network.")
        assert isinstance(value, str)
        assert value not in {"mock", "section"}


@pytest.mark.asyncio
async def test_mock_uci_sample_is_stable_for_every_allowlisted_config(
    mock_explorer: MockOpenWRTExplorer,
) -> None:
    for config in ("network", "dhcp", "wireless", "firewall", "system", "dropbear"):
        result = await mock_explorer.read_uci_config(config)
        assert result["success"] is True
        assert len(result["sample"]) > 0


@pytest.mark.asyncio
async def test_mock_dhcp_details_resolve_own_lease(
    mock_explorer: MockOpenWRTExplorer,
) -> None:
    leases = await mock_explorer.list_dhcp_leases()
    lease = leases["leases"][0]
    by_ip = await mock_explorer.get_device_dhcp_details(None, lease["ip"])
    assert by_ip["is_currently_connected"] is True
    assert by_ip["current_lease"]["mac"] == lease["mac"]
    assert by_ip["recent_log_events"], "expected dnsmasq events for the mock client"
    assert by_ip["recent_log_events"][0]["event_type"] == "ack"

    by_mac = await mock_explorer.get_device_dhcp_details(lease["mac"], None)
    assert by_mac["current_lease"]["ip"] == lease["ip"]


@pytest.mark.asyncio
async def test_mock_unknown_device_has_no_lease(mock_explorer: MockOpenWRTExplorer) -> None:
    result = await mock_explorer.get_device_dhcp_details(None, "192.0.2.250")
    assert result["is_currently_connected"] is False
    assert result["current_lease"] is None
    assert result["recent_log_events"] == []


@pytest.mark.asyncio
async def test_mock_log_lines_look_like_logread_output(
    mock_explorer: MockOpenWRTExplorer,
) -> None:
    result = await mock_explorer.get_router_logs(50, "all")
    assert result["success"] is True
    lines = result["logs"].splitlines()
    assert lines, "expected at least one log line"
    assert "logread" not in lines[0].lower()
    assert "daemon.info" in lines[0] or "kern.info" in lines[0]


@pytest.mark.asyncio
async def test_mock_search_router_logs_returns_matching_lines(
    mock_explorer: MockOpenWRTExplorer,
) -> None:
    result = await mock_explorer.search_router_logs("dnsmasq", 10)
    assert result["success"] is True
    assert result["results_count"] >= 1
    assert "dnsmasq" in result["results"].casefold()


@pytest.mark.asyncio
async def test_mock_wifi_scan_contains_real_scan_fields(
    mock_explorer: MockOpenWRTExplorer,
) -> None:
    result = await mock_explorer.wifi_scan("wlan0")
    assert result["success"] is True
    network = result["networks"][0]
    for field in ("bssid", "ssid", "channel", "signal", "mode"):
        assert field in network, f"wifi_scan network missing {field!r}"


@pytest.mark.asyncio
async def test_mock_ping_output_contains_real_ping_statistics(
    mock_explorer: MockOpenWRTExplorer,
) -> None:
    result = await mock_explorer.ping_host("8.8.8.8", 2)
    assert result["success"] is True
    assert "packets transmitted" in result["output"]
    assert "rtt min/avg/max/mdev" in result["output"]
