"""Centralized input validation for OpenWRT MCP tools."""

import re


class ValidationError(Exception):
    """Raised when input fails validation."""


class SecurityValidator:
    """
    Whitelist-based command validator to prevent command injection.
    All operations are read-only (no system modifications).

    SECURITY: This class is critical for system safety.
    """

    # ALLOWED READ-ONLY COMMANDS
    ALLOWED_PATTERNS = [
        # UBUS – OpenWRT system services (status/info only)
        r"^ubus call system board$",
        r"^ubus call system info$",
        r"^ubus call network\.interface\.\w+ status$",
        r"^ubus call network\.wireless status$",
        r"^ubus list$",
        r"^ubus list .+$",
        # UCI – configuration (read-only)
        r"^uci show$",
        r"^uci show [a-zA-Z0-9._-]+$",
        r"^uci get [a-zA-Z0-9._@:\[\]-]+$",
        # DHCP – lease list
        r"^cat /tmp/dhcp\.leases$",
        r"^cat /var/dhcp\.leases$",
        # Firewall – rules (read-only)
        r"^iptables -L -n -v$",
        r"^iptables -L -n -v -t nat$",
        r"^iptables -L -n -v -t mangle$",
        r"^nft list ruleset(?: 2>/dev/null)?$",
        r"^fw4 status(?: 2>/dev/null)?$",
        # System logs
        r"^logread$",
        r"^logread -e [a-zA-Z0-9._-]+$",
        r"^logread -l \d+$",
        # System information
        r"^cat /proc/meminfo$",
        r"^cat /proc/cpuinfo$",
        r"^cat /proc/uptime$",
        r"^cat /proc/1/comm$",
        r"^cat /etc/openwrt_version$",
        r"^cat /etc/openwrt_release$",
        r"^df -h$",
        r"^free$",
        r"^top -bn1$",
        r"^ps$",
        # Network configuration
        r"^ip addr show$",
        r"^ip route show$",
        r"^iwinfo$",
        r"^iwinfo .+ info$",
        r"^iw dev$",
        # Network diagnostics
        r"^ping -c \d+(?: -W \d+)? [\w\.\-]+$",
        r"^nslookup [\w\.\-]+(?: [\w\.\-]+)?$",
        r"^traceroute -n [\w\.\-]+$",
        r"^traceroute [\w\.\-]+$",
        # WiFi scan (read-only)
        r"^iwinfo .+ scan$",
        r"^iw dev .+ scan$",
        # System load
        r"^cat /proc/loadavg$",
        # Packages (OPKG) – READ-ONLY ONLY
        r"^opkg list$",
        r"^opkg list-installed$",
        r"^opkg list-upgradable$",
        r"^opkg info [a-zA-Z0-9._-]+$",
        r"^opkg search [a-zA-Z0-9._-]+$",
    ]

    DANGEROUS_METACHARACTERS = [
        ";",
        "&&",
        "||",
        "|",
        "$(",
        "`",
        "$",
        "{",
        "}",
    ]

    BLOCKED_PATTERNS = [
        r"rm\s+-",
        r"dd\s+",
        r"mkfs",
        r"uci\s+(set|add|remove|delete|rename|revert|commit)",
        r"opkg\s+(install|remove|upgrade|update|configure)",
        r"reboot",
        r"halt",
        r"poweroff",
        r"wget\s+",
        r"curl\s+",
        r">\s*/(?!dev/null)",
        r"\|\s*sh",
        r"\|\s*bash",
        r"\|\s*ash",
        r";\s*",
        r"\$\(",
        r"\$\{",
        r"`",
        r"mv\s+",
        r"chmod\s+",
        r"chown\s+",
        r">\s*[^/\s]",
        r"<\s*[^/\s]",
    ]

    @classmethod
    def validate_command(cls, command: str) -> tuple[bool, str]:
        """Validate command before execution.

        SECURITY: First line of defense against command injection.

        Returns:
            (allowed: bool, message: str)
        """
        if not command or not isinstance(command, str):
            return False, "Empty or invalid command"

        cmd_stripped = command.strip()
        cmd_lower = cmd_stripped.lower()

        for char in cls.DANGEROUS_METACHARACTERS:
            if char in cmd_stripped:
                if char == ">" and re.search(r"2>/dev/null", cmd_stripped):
                    continue
                return False, f"Blocked dangerous character: '{char}'"

        for pattern in cls.BLOCKED_PATTERNS:
            if re.search(pattern, cmd_lower):
                return False, f"Blocked dangerous operation matching: '{pattern}'"

        for pattern in cls.ALLOWED_PATTERNS:
            if re.fullmatch(pattern, cmd_stripped):
                return True, "Command approved"

        return False, (
            f"Unsupported command: '{cmd_stripped[:50]}...'\n"
            f"Allowed: system info, WiFi status, DHCP leases, firewall rules, "
            f"UCI configuration (read-only), package lists, network diagnostics"
        )

    # ALLOWED WRITE-ONLY COMMANDS (guarded by ENABLE_WRITE_OPERATIONS=1)
    ALLOWED_WRITE_PATTERNS = [
        r"^ifdown [a-z][a-z0-9._-]{0,14}$",
        r"^ifup [a-z][a-z0-9._-]{0,14}$",
        r"^/etc/init\.d/network (?:reload|restart)$",
        r"^uci set [a-zA-Z0-9._-]+\.@?[a-zA-Z0-9._-]+\[\d+\]\.[a-zA-Z0-9._-]+=[^\s]+$",
        r"^uci set [a-zA-Z0-9._-]+\.[a-zA-Z0-9._-]+\.[a-zA-Z0-9._-]+=[^\s]+$",
        r"^uci commit [a-zA-Z0-9._-]+$",
        r"^ubus call system reboot$",
    ]

    @classmethod
    def validate_write_command(cls, command: str) -> tuple[bool, str]:
        """Validate a write-mode command before execution.

        Only active when ENABLE_WRITE_OPERATIONS=1.
        Uses its own allowlist of safe write operations.
        """
        if not command or not isinstance(command, str):
            return False, "Empty or invalid command"

        cmd_stripped = command.strip()

        for pattern in cls.ALLOWED_WRITE_PATTERNS:
            if re.fullmatch(pattern, cmd_stripped):
                return True, "Command approved"

        return False, (
            f"Unsupported write command: '{cmd_stripped[:50]}'\n"
            f"Allowed: ifdown <interface>, ifup <interface>, /etc/init.d/network reload|restart"
        )

    @classmethod
    def validate_interface_name(cls, name: str) -> str:
        """Validate a network interface name (e.g. 'wan', 'lan', 'wwan0')."""
        if not name or not re.match(r"^[a-z][a-z0-9._-]{0,14}$", name):
            raise ValidationError(
                f"Invalid interface name: '{name}'. "
                "Must start with a letter and contain only lowercase"
                " letters, digits, dots, underscores, or hyphens."
            )
        BLOCKED_INTERFACES = {"lo", "lo0"}
        if name.lower() in BLOCKED_INTERFACES:
            raise ValidationError(f"Interface '{name}' is blocked from restart")
        return name

    @classmethod
    def sanitize_command(cls, command: str) -> str:
        """Remove potentially dangerous characters from a command string.

        SECURITY: Second line of defense against command injection.

        Returns:
            Sanitized command (may be empty if everything is removed).
        """
        if not command:
            return ""

        dangerous_chars = [
            ";",
            "&",
            "|",
            "$",
            "`",
            "(",
            ")",
            "{",
            "}",
            "<",
            ">",
            "\n",
            "\r",
            "\\",
            "\0",
            "'",
            '"',
        ]

        sanitized = command
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, " ")

        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        return sanitized

    @classmethod
    def is_safe_search_term(cls, term: str) -> bool:
        """Check whether a search term is safe.

        Used by search_router_logs, search_dhcp_logs, etc.

        Returns:
            True if term is safe, False otherwise.
        """
        if not term or len(term) > 100:
            return False

        if not re.match(r"^[a-zA-Z0-9\s\.\-\:_]+$", term):
            return False

        dangerous_sequences = [";", "&&", "||", "|", "$", "`", "(", ")", "{", "}", "<", ">"]
        for seq in dangerous_sequences:
            if seq in term:
                return False

        return True
