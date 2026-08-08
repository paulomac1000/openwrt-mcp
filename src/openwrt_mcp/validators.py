"""Central input and fixed-command validation."""

from __future__ import annotations

import ipaddress
import re
import shlex


class ValidationError(Exception):
    """Raised when input fails validation."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9._@\[\]-]{1,128}$")
_CONFIG = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_INTERFACE = re.compile(r"^[a-z][a-z0-9._-]{0,14}$")
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$")
_MAC = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
_DANGEROUS_VALUE = re.compile(r"[\x00-\x1f\x7f;&|`$<>\\]")


class SecurityValidator:
    """Allowlist validator for values and commands executed on the router."""

    READABLE_UCI_CONFIGS = frozenset(
        {
            "dhcp",
            "network",
            "wireless",
            "firewall",
            "system",
            "dropbear",
            "luci",
            "uhttpd",
            "rpcd",
            "ucitrack",
            "ubootenv",
        }
    )

    ALLOWED_PATTERNS = [
        r"^ubus call system board$",
        r"^ubus call system info$",
        r"^ubus call network\.interface\.\w+ status$",
        r"^ubus call network\.wireless status$",
        r"^ubus list$",
        r"^uci show(?: [a-zA-Z0-9._-]+)?$",
        r"^uci get [a-zA-Z0-9._@:\[\]-]+$",
        r"^cat /(?:tmp|var)/dhcp\.leases$",
        r"^iptables -L -n -v(?: -t (?:nat|mangle))?$",
        r"^nft list ruleset$",
        r"^fw4 status$",
        r"^logread(?: -l \d+|-e [a-zA-Z0-9._-]+)?$",
        r"^cat /proc/(?:meminfo|cpuinfo|uptime|loadavg|1/comm)$",
        r"^cat /etc/openwrt_(?:version|release)$",
        r"^(?:df -h|free|top -bn1|ps|ip addr show|ip route show|iwinfo|iw dev)$",
        r"^iwinfo [A-Za-z0-9._-]+ (?:info|scan)$",
        r"^iw dev [A-Za-z0-9._-]+ scan$",
        r"^ping -c \d+(?: -W \d+)? [\w.:-]+$",
        r"^nslookup [\w.:-]+(?: [\w.:-]+)?$",
        r"^traceroute(?: -n)? [\w.:-]+$",
        r"^opkg (?:list|list-installed|list-upgradable)$",
        r"^opkg (?:info|search) [a-zA-Z0-9._-]+$",
    ]

    @classmethod
    def validate_command(cls, command: str) -> tuple[bool, str]:
        if not isinstance(command, str) or not command.strip():
            return False, "Empty or invalid command"
        candidate = command.strip()
        if re.search(r"[;&|`$<>\\(){}\n\r\x00]", candidate):
            return False, "Shell control characters are forbidden"
        for pattern in cls.ALLOWED_PATTERNS:
            if re.fullmatch(pattern, candidate):
                return True, "Command approved"
        return False, "Unsupported read command"

    @classmethod
    def validate_host_or_address(cls, value: str) -> str:
        if not isinstance(value, str) or not _HOST.fullmatch(value):
            raise ValidationError("Invalid host or address")
        return value

    @classmethod
    def validate_device_identifier(
        cls,
        mac_address: str | None,
        ip_address: str | None,
    ) -> str:
        if not mac_address and not ip_address:
            raise ValidationError("Provide device MAC or IP")
        if mac_address:
            normalized = mac_address.lower().replace("-", ":")
            if not _MAC.fullmatch(normalized):
                raise ValidationError("Invalid MAC address format")
            return normalized
        assert ip_address is not None
        try:
            return str(ipaddress.ip_address(ip_address))
        except ValueError as exc:
            raise ValidationError("Invalid IP address format") from exc

    @classmethod
    def validate_interface_name(cls, name: str) -> str:
        if not isinstance(name, str) or not _INTERFACE.fullmatch(name):
            raise ValidationError("Invalid interface name")
        if name in {"lo", "lo0"}:
            raise ValidationError("Loopback interfaces cannot be restarted")
        return name

    @classmethod
    def validate_uci_config(cls, value: str) -> str:
        if not isinstance(value, str) or not _CONFIG.fullmatch(value):
            raise ValidationError("Invalid UCI configuration identifier")
        return value

    @classmethod
    def validate_readable_uci_config(cls, value: str) -> str:
        config = cls.validate_uci_config(value)
        if config not in cls.READABLE_UCI_CONFIGS:
            allowed = ", ".join(sorted(cls.READABLE_UCI_CONFIGS))
            raise ValidationError(f"Configuration {config!r} not supported. Allowed: {allowed}")
        return config

    @classmethod
    def validate_uci_identifier(cls, value: str, *, field: str) -> str:
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise ValidationError(f"Invalid UCI {field}")
        return value

    @classmethod
    def validate_uci_value(cls, value: str) -> str:
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
            raise ValidationError("UCI value must contain 1-512 UTF-8 bytes")
        if _DANGEROUS_VALUE.search(value):
            raise ValidationError("UCI value contains shell control characters")
        return value

    @classmethod
    def build_uci_set_command(cls, config: str, section: str, option: str, value: str) -> str:
        config = cls.validate_uci_config(config)
        section = cls.validate_uci_identifier(section, field="section")
        option = cls.validate_uci_identifier(option, field="option")
        value = cls.validate_uci_value(value)
        assignment = f"{config}.{section}.{option}={value}"
        return f"uci set {shlex.quote(assignment)}"

    @classmethod
    def validate_write_command(cls, command: str) -> tuple[bool, str]:
        if not isinstance(command, str) or not command.strip():
            return False, "Empty or invalid command"
        if any(control in command for control in ("\n", "\r", "\x00")):
            return False, "Control characters are forbidden"
        try:
            argv = shlex.split(command, posix=True)
        except ValueError:
            return False, "Malformed command quoting"

        try:
            if len(argv) == 2 and argv[0] in {"ifdown", "ifup"}:
                cls.validate_interface_name(argv[1])
                return True, "Command approved"
            if argv in (["/etc/init.d/network", "reload"], ["/etc/init.d/network", "restart"]):
                return True, "Command approved"
            if len(argv) == 3 and argv[:2] == ["uci", "set"]:
                path, separator, value = argv[2].partition("=")
                if not separator:
                    raise ValidationError("Missing UCI assignment")
                parts = path.split(".")
                if len(parts) != 3:
                    raise ValidationError("UCI assignment must be config.section.option")
                cls.validate_uci_config(parts[0])
                cls.validate_uci_identifier(parts[1], field="section")
                cls.validate_uci_identifier(parts[2], field="option")
                cls.validate_uci_value(value)
                return True, "Command approved"
            if len(argv) == 3 and argv[:2] == ["uci", "commit"]:
                cls.validate_uci_config(argv[2])
                return True, "Command approved"
            if argv == ["ubus", "call", "system", "reboot"]:
                return True, "Command approved"
        except ValidationError as exc:
            return False, str(exc)
        return False, "Unsupported write command"

    @staticmethod
    def is_safe_search_term(term: str) -> bool:
        return bool(
            isinstance(term, str)
            and 0 < len(term) <= 100
            and re.fullmatch(r"[A-Za-z0-9 .\-:_]+", term)
        )
