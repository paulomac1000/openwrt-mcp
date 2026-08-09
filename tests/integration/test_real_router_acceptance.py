"""Executable acceptance tests for an isolated real OpenWRT laboratory."""

from __future__ import annotations

import asyncio
import ipaddress
import os
from dataclasses import replace
from pathlib import Path

import pytest

from openwrt_mcp.application import CapabilityManifest, CapabilityRegistry, InvocationKernel
from openwrt_mcp.server import build_application
from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.explorer import OpenWRTExplorer
from openwrt_mcp.tools.ssh_client import SSHConnection

pytestmark = [pytest.mark.integration, pytest.mark.lab]


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture
def lab_settings() -> Settings:
    if not _enabled(os.getenv("OPENWRT_LAB_RUN")):
        pytest.skip(
            "real-router acceptance disabled; set OPENWRT_LAB_RUN=1 with the production "
            "OPENWRT_HOST/USER/SSH_KEY/KNOWN_HOSTS environment"
        )
    settings = Settings.from_env()
    if settings.mock_mode:
        pytest.fail("OPENWRT_LAB_RUN=1 requires OPENWRT_MOCK_MODE=0")
    if settings.insecure_skip_host_key_check:
        pytest.fail("real-router acceptance requires SSH host-key verification")
    return replace(settings, enable_audit_logging=False)


def _slow_target() -> str:
    target = os.getenv("OPENWRT_LAB_SLOW_TARGET", "").strip()
    if not target:
        pytest.skip(
            "set OPENWRT_LAB_SLOW_TARGET to an allowlisted IP that remains unreachable "
            "long enough for cancellation/timeout testing"
        )
    return target


def _device_ip(settings: Settings) -> str:
    candidate = os.getenv("OPENWRT_LAB_DEVICE_IP", settings.openwrt_host).strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pytest.fail(
            "OPENWRT_LAB_DEVICE_IP must be set to a valid IPv4/IPv6 address when "
            "OPENWRT_HOST is not an IP literal"
        )


def _wrong_known_hosts(path: Path, settings: Settings) -> Path:
    import asyncssh

    public = asyncssh.generate_private_key("ssh-ed25519").export_public_key().strip()
    host = (
        settings.openwrt_host
        if settings.openwrt_port == 22
        else f"[{settings.openwrt_host}]:{settings.openwrt_port}"
    )
    path.write_bytes(host.encode("utf-8") + b" " + public + b"\n")
    return path


@pytest.mark.asyncio
async def test_real_router_wrong_host_key_never_opens_command_session(
    lab_settings: Settings, tmp_path: Path
) -> None:
    wrong = _wrong_known_hosts(tmp_path / "known_hosts.wrong", lab_settings)
    client = SSHConnection(
        replace(
            lab_settings,
            openwrt_known_hosts=wrong,
            insecure_skip_host_key_check=False,
        )
    )
    try:
        assert await client.connect() is False
        stdout, error, code = await client.execute("ubus call system board")
        assert (stdout, error, code) == ("", "No SSH connection", 1)
        assert client._connection is None  # noqa: SLF001
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_router_official_mcp_read_smoke(lab_settings: Settings) -> None:
    from mcp import Client

    app = build_application(lab_settings)
    try:
        async with Client(app.mcp) as client:
            listing = await client.list_tools()
            names = {tool.name for tool in listing.tools}
            assert len(names) == 19
            assert "uci_set" not in names
            assert all(
                tool.input_schema.get("additionalProperties") is False for tool in listing.tools
            )

            connected = await client.call_tool("test_router_connection", {})
            info = await client.call_tool("get_router_info", {})
            assert connected.is_error is False
            assert info.is_error is False
            assert connected.structured_content is not None
            assert info.structured_content is not None
            assert connected.structured_content["data"]["status"] == "connected"
            assert info.structured_content["data"]["hostname"]
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_real_router_all_active_tools_execute_successfully(lab_settings: Settings) -> None:
    """Prove every advertised L1 tool is actually executable on the lab target."""
    from mcp import Client

    device_ip = _device_ip(lab_settings)
    diagnostic_host = os.getenv("OPENWRT_LAB_DIAGNOSTIC_HOST", "127.0.0.1").strip()
    dns_name = os.getenv("OPENWRT_LAB_DNS_NAME", "openwrt.lan").strip()
    dns_server = os.getenv("OPENWRT_LAB_DNS_SERVER", "127.0.0.1").strip()
    wifi_radio = os.getenv("OPENWRT_LAB_WIFI_RADIO", "wlan0").strip()
    search_term = os.getenv("OPENWRT_LAB_SEARCH_TERM", "dnsmasq").strip()

    calls: dict[str, dict[str, object]] = {
        "test_router_connection": {},
        "get_router_info": {},
        "get_router_wifi_status": {},
        "get_router_dhcp_leases": {},
        "get_router_firewall_rules": {},
        "read_router_uci_config": {"config_name": "network"},
        "list_router_packages": {},
        "get_router_logs": {"lines": 20, "filter_level": "all"},
        "search_router_logs": {"search_term": search_term, "max_results": 10},
        "diagnose_router_connectivity": {},
        "get_dhcp_static_leases": {},
        "search_dhcp_logs": {"search_term": search_term},
        "get_device_dhcp_details": {"ip_address": device_ip},
        "get_router_context": {},
        "describe_router_capabilities": {},
        "ping_host": {"host": diagnostic_host, "count": 1},
        "traceroute_host": {"host": diagnostic_host},
        "nslookup_host": {"host": dns_name, "dns_server": dns_server},
        "wifi_scan": {"radio": wifi_radio},
    }

    app = build_application(lab_settings)
    failures: dict[str, object] = {}
    try:
        async with Client(app.mcp) as client:
            listing = await client.list_tools()
            advertised = {tool.name for tool in listing.tools}
            assert advertised == set(calls)
            for name, arguments in calls.items():
                result = await client.call_tool(name, arguments)
                if result.is_error:
                    failures[name] = result.structured_content or [
                        getattr(item, "text", "") for item in result.content
                    ]
    finally:
        await app.close()

    assert failures == {}, f"active tools failed on real router: {failures}"


async def _assert_no_ping_process(client: SSHConnection, target: str) -> None:
    await asyncio.sleep(0.25)
    output, _, code = await client.execute("ps")
    assert code == 0
    assert target not in output, f"orphaned ping process still references {target}"


@pytest.mark.asyncio
async def test_real_router_cancellation_closes_session_and_kills_remote_command(
    lab_settings: Settings,
) -> None:
    target = _slow_target()
    client = SSHConnection(lab_settings)
    try:
        task = asyncio.create_task(client.execute(f"ping -c 30 -W 2 {target}"))
        await asyncio.sleep(0.25)
        assert not task.done(), (
            "OPENWRT_LAB_SLOW_TARGET completed too quickly; choose a routed blackhole target"
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client._connection is None  # noqa: SLF001
        assert await client.connect() is True
        await _assert_no_ping_process(client, target)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_router_timeout_closes_session_and_kills_remote_command(
    lab_settings: Settings,
) -> None:
    target = _slow_target()
    client = SSHConnection(lab_settings)
    try:
        _, error, code = await client.execute(
            f"ping -c 30 -W 2 {target}",
            timeout_seconds=1,
        )
        assert (code, error) == (124, "Timeout after 1s")
        assert client._connection is None  # noqa: SLF001
        assert await client.connect() is True
        await _assert_no_ping_process(client, target)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_router_response_byte_limit_is_enforced(lab_settings: Settings) -> None:
    explorer = OpenWRTExplorer(lab_settings)
    manifest = CapabilityManifest(
        name="real_system_info_probe",
        version="lab",
        risk="READ",
        side_effects="read",
        confidentiality="sensitive",
        operational_impact="none",
        cost="cheap",
        idempotent=False,
        retryable=False,
        concurrent_safe=False,
        timeout_ms=15_000,
        requires_confirmation=False,
        reversible=False,
        max_response_bytes=128,
    )
    kernel = InvocationKernel(
        registry=CapabilityRegistry({manifest.name: manifest}),
        operations={manifest.name: explorer.get_system_info},
        target_identity=(
            f"ssh:{lab_settings.openwrt_user}@{lab_settings.openwrt_host}:"
            f"{lab_settings.openwrt_port}"
        ),
    )
    try:
        result = await kernel.invoke(manifest.name, {})
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "RESPONSE_TOO_LARGE"
    finally:
        await explorer.ssh.close()
