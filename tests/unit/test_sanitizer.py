from openwrt_mcp.sanitizer import sanitize_log_line, sanitize_response_data


def test_log_sanitizer_redacts_secret_ip_and_mac_boundaries() -> None:
    rendered = sanitize_log_line(
        "auth_token=abc private_key=def password=ghi 192.0.2.10 2001:db8::1 aa:bb:cc:dd:ee:ff"
    )
    assert "abc" not in rendered
    assert "def" not in rendered
    assert "ghi" not in rendered
    assert "192.0.2.10" not in rendered
    assert "2001:db8::1" not in rendered
    assert "aa:bb:cc:dd:ee:ff" not in rendered
    assert rendered.count("<REDACTED>") == 3
    assert rendered.count("<IP_REDACTED>") == 2
    assert "<MAC_REDACTED>" in rendered


def test_response_sanitizer_catches_composite_secret_keys_without_over_redacting() -> None:
    data = {
        "auth_token": "one",
        "private-key": "two",
        "wireless.radio0.key": "three",
        "monkey": "banana",
        "nested": [{"api_key": "four"}],
    }
    sanitized = sanitize_response_data(data)
    assert sanitized["auth_token"] == "<REDACTED>"
    assert sanitized["private-key"] == "<REDACTED>"
    assert sanitized["wireless.radio0.key"] == "<REDACTED>"
    assert sanitized["monkey"] == "banana"
    assert sanitized["nested"][0]["api_key"] == "<REDACTED>"


def test_passphrases_and_private_keys_do_not_cross_output_boundaries() -> None:
    canary = "synthetic-canary-51ad"
    data = {"nested": [{"wpa_passphrase": canary}], "text": f"passphrase='{canary} two'"}
    assert canary not in repr(sanitize_response_data(data))
    assert canary not in sanitize_log_line(data["text"])
    pem = f"-----BEGIN OPENSSH PRIVATE KEY-----\n{canary}\n-----END OPENSSH PRIVATE KEY-----"
    assert canary not in sanitize_log_line(pem)


def test_url_credentials_do_not_cross_output_boundaries() -> None:
    url = "https://synthetic-user:synthetic-canary-94af@example.test/path"
    for rendered in (sanitize_log_line(url), sanitize_response_data(url)):
        assert "synthetic-user" not in rendered
        assert "synthetic-canary-94af" not in rendered
        assert "example.test/path" in rendered
