from __future__ import annotations

import shlex

import pytest

from openwrt_mcp.validators import SecurityValidator, ValidationError


@pytest.mark.parametrize(
    "value",
    [
        "x;reboot",
        "x&&reboot",
        "$(reboot)",
        "`reboot`",
        "x|sh",
        "x\nreboot",
        "x\rreboot",
        "x\\reboot",
        "x>file",
        "x<file",
    ],
)
def test_uci_value_blocks_shell_control(value: str) -> None:
    with pytest.raises(ValidationError):
        SecurityValidator.build_uci_set_command("network", "wan", "ipaddr", value)


def test_uci_command_quotes_spaces_without_exposing_shell_syntax() -> None:
    command = SecurityValidator.build_uci_set_command(
        "wireless", "default_radio0", "ssid", "Trusted guest network"
    )
    assert shlex.split(command) == [
        "uci",
        "set",
        "wireless.default_radio0.ssid=Trusted guest network",
    ]
    assert SecurityValidator.validate_write_command(command)[0] is True


def test_write_validator_rejects_unquoted_injection() -> None:
    allowed, _ = SecurityValidator.validate_write_command(
        "uci set network.wan.ipaddr=192.0.2.1;reboot"
    )
    assert allowed is False


def test_write_validator_rejects_option_and_path_confusion() -> None:
    for command in (
        "uci set -q=x",
        "uci commit ../../etc/passwd",
        "ifup --help",
        "ubus call system reboot extra",
    ):
        assert SecurityValidator.validate_write_command(command)[0] is False


def test_read_validator_remains_allowlist_only() -> None:
    assert SecurityValidator.validate_command("ubus call system board")[0] is True
    assert SecurityValidator.validate_command("cat /etc/shadow")[0] is False

@pytest.mark.parametrize(
    "command",
    [
        "ubus list > /tmp/leak",
        "ubus list $(reboot)",
        "ubus list foo\\bar",
        "nft list ruleset 2>/dev/null",
        "ping -c 1 8.8.8.8 & reboot",
    ],
)
def test_read_command_rejects_shell_syntax(command: str) -> None:
    allowed, _ = SecurityValidator.validate_command(command)
    assert allowed is False

