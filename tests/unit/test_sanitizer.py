"""Unit tests for the secret sanitizer (Canonical Templates 4a/4b)."""

from openwrt_mcp.sanitizer import sanitize_log_line, sanitize_response_data


class TestSanitizeLogLine:
    """sanitize_log_line() redacts credentials and IP addresses."""

    def test_redacts_bearer_token(self):
        out = sanitize_log_line("auth header Bearer abc123XYZ._-token")
        assert "abc123XYZ" not in out
        assert "<REDACTED>" in out

    def test_redacts_authorization_header(self):
        out = sanitize_log_line("Authorization: Basic dXNlcjpwYXNz")
        assert "dXNlcjpwYXNz" not in out

    def test_redacts_password_assignment(self):
        out = sanitize_log_line("connecting with password=hunter2 now")
        assert "hunter2" not in out
        assert "<REDACTED>" in out

    def test_redacts_ip_address(self):
        out = sanitize_log_line("SSH connection established: root@192.168.0.1")
        assert "192.168.0.1" not in out
        assert "<IP_REDACTED>" in out

    def test_preserves_plain_text(self):
        assert sanitize_log_line("router rebooted cleanly") == "router rebooted cleanly"


class TestSanitizeResponseData:
    """sanitize_response_data() redacts secrets but PRESERVES IP/MAC."""

    def test_preserves_ip_addresses(self):
        data = {"ip": "192.168.0.50", "mac": "aa:bb:cc:dd:ee:ff"}
        out = sanitize_response_data(data)
        assert out["ip"] == "192.168.0.50"
        assert out["mac"] == "aa:bb:cc:dd:ee:ff"

    def test_redacts_secret_named_key(self):
        data = {"key": "supersecretpsk", "ssid": "HomeNet"}
        out = sanitize_response_data(data)
        assert out["key"] == "<REDACTED>"
        assert out["ssid"] == "HomeNet"

    def test_redacts_uci_flat_line(self):
        line = "wireless.@wifi-iface[0].key='supersecretpsk'"
        out = sanitize_response_data(line)
        assert "supersecretpsk" not in out
        assert "<REDACTED>" in out

    def test_recurses_into_nested_structures(self):
        data = {"leases": [{"ip": "10.0.0.2", "password": "leak"}]}
        out = sanitize_response_data(data)
        assert out["leases"][0]["ip"] == "10.0.0.2"
        assert out["leases"][0]["password"] == "<REDACTED>"

    def test_passes_through_non_string_scalars(self):
        data = {"count": 5, "ok": True, "ratio": 1.5, "missing": None}
        assert sanitize_response_data(data) == data

    def test_does_not_redact_innocuous_keys(self):
        data = {"hostname": "router", "monkey": "value"}
        out = sanitize_response_data(data)
        assert out["hostname"] == "router"
        assert out["monkey"] == "value"
