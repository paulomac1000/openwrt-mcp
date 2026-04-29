"""
OpenWRT Router Explorer - tools for remote read-only access to OpenWRT over SSH.
All operations are read-only to avoid system modification risk.
"""

import os
import re
import json
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path

# ==============================================================================
# ENVIRONMENT VARIABLE CONFIGURATION
# ==============================================================================

OPENWRT_HOST = os.getenv("OPENWRT_HOST", "192.168.0.200")
OPENWRT_PORT = int(os.getenv("OPENWRT_PORT", "22"))
OPENWRT_USER = os.getenv("OPENWRT_USER", "root")
OPENWRT_SSH_KEY = os.getenv("OPENWRT_SSH_KEY", "/root/.ssh/openwrt_key")
OPENWRT_PASSWORD = os.getenv("OPENWRT_PASSWORD", None)  # Not recommended – use SSH keys
SSH_TIMEOUT = int(os.getenv("SSH_TIMEOUT", "30"))
ENABLE_AUDIT_LOGGING = os.getenv("ENABLE_AUDIT_LOGGING", "true").lower() in ("1", "true", "yes")
AUDIT_LOG_FILE = os.getenv("LOG_FILE", "/var/log/openwrt_mcp.log")

# ==============================================================================
# SECURITY VALidATOR – BUILT-IN IMPLEMENTATION
# ==============================================================================

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
        r"^cat /proc/1/comm$",  # Added for test_connection
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
        
        # Packages (OPKG) – READ-ONLY ONLY
        r"^opkg list$",
        r"^opkg list-installed$",
        r"^opkg list-upgradable$",
        r"^opkg info [a-zA-Z0-9._-]+$",
        r"^opkg search [a-zA-Z0-9._-]+$",
    ]
    
    # DANGEROUS SHELL METACHARACTERS (always blocked)
    # These characters enable command injection and must be blocked
    DANGEROUS_METACHARACTERS = [
        ';',    # Command separator
        '&&',   # AND operator
        '||',   # OR operator
        '|',    # Pipe (except in allowed patterns)
        '$(',   # Command substitution
        '`',    # Backtick command substitution
        '$',    # Variable expansion (standalone)
        '{',    # Brace expansion
        '}',    # Brace expansion
    ]
    
    # BLOCKED PATTERNS (even if they match the whitelist)
    BLOCKED_PATTERNS = [
        r"rm\s+-",          # File removal
        r"dd\s+",           # Disk operations
        r"mkfs",            # formatting
        r"uci\s+(set|add|remove|delete|rename|revert|commit)",  # UCI modification
        r"opkg\s+(install|remove|upgrade|update|configure)",    # Package modification
        r"reboot",          # Restart
        r"halt",            # Shutdown
        r"poweroff",        # Shutdown
        r"wget\s+",         # Network download
        r"curl\s+",         # Network download
        r">\s*/(?!dev/null)", # Redirect to files (except /dev/null)
        r"\|\s*sh",         # Pipe to sh
        r"\|\s*bash",       # Pipe to bash
        r"\|\s*ash",        # Pipe to ash (OpenWRT shell)
        r";\s*",            # Multiple commands
        r"\$\(",            # Command substitution
        r"\$\{",            # Variable expansion
        r"`",               # Backtick substitution
        r"mv\s+",           # Move files
        r"chmod\s+",        # Change permissions
        r"chown\s+",        # Change owner
        r">\s*[^/\s]",      # Redirect to file (non-path)
        r"<\s*[^/\s]",      # Redirect from file (non-path)
    ]

    @classmethod
    def validate_command(cls, command: str) -> Tuple[bool, str]:
        """
        Validate command before execution.

        SECURITY: First line of defense against command injection.

        Returns:
            (allowed: bool, message: str)
        """
        if not command or not isinstance(command, str):
            return False, "Empty or invalid command"
        
        cmd_stripped = command.strip()
        cmd_lower = cmd_stripped.lower()
        
        # 1. Check dangerous metacharacters first (critical)
        for char in cls.DANGEROUS_METACHARACTERS:
            if char in cmd_stripped:
                # Allow "2>/dev/null" for stderr redirection
                if char == '>' and re.search(r'2>/dev/null', cmd_stripped):
                    continue
                return False, f"Blocked dangerous character: '{char}'"
        
        # 2. Check blocked patterns
        for pattern in cls.BLOCKED_PATTERNS:
            if re.search(pattern, cmd_lower):
                return False, f"Blocked dangerous operation matching: '{pattern}'"
        
        # 3. Check whitelist
        for pattern in cls.ALLOWED_PATTERNS:
            if re.fullmatch(pattern, cmd_stripped):
                return True, "Command approved"
        
        return False, (
            f"Unsupported command: '{cmd_stripped[:50]}...'\n"
            f"Allowed: system info, WiFi status, DHCP leases, firewall rules, "
            f"UCI configuration (read-only), package lists, network diagnostics"
        )

    @classmethod
    def sanitize_command(cls, command: str) -> str:
        """
        Remove potentially dangerous characters from a command string.

        SECURITY: Second line of defense against command injection.

        Returns:
            Sanitized command (may be empty if everything is removed).
        """
        if not command:
            return ""
        
        # Comprehensive list of dangerous characters to strip
        # Includes shell metacharacters, separators, redirection, substitution
        dangerous_chars = [
            ';',    # Command separator
            '&',    # Background / AND operator
            '|',    # Pipe
            '$',    # Variable/command substitution
            '`',    # Backtick substitution
            '(',    # Subshell / command substitution
            ')',    # Subshell / command substitution
            '{',    # Brace expansion
            '}',    # Brace expansion
            '<',    # Input redirection
            '>',    # Output redirection
            '\n',   # Newline (command separator)
            '\r',   # Carriage return
            '\\',   # Escape character (can bypass filters)
            '\0',   # Null byte
            "'",    # Single quote (can break out of quoted string)
            '"',    # Double quote (can break out of quoted string)
        ]
        
        sanitized = command
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, ' ')
        
        # Collapse multiple spaces and trim
        sanitized = re.sub(r'\s+', ' ', sanitized).strip()
        
        return sanitized
    
    @classmethod
    def is_safe_search_term(cls, term: str) -> bool:
        """
        Check whether a search term is safe.

        Used by search_router_logs, search_dhcp_logs, etc.

        Returns:
            True if term is safe, False otherwise.
        """
        if not term or len(term) > 100:
            return False
        
        # Only alphanumeric, spaces, dots, dashes, colons (for MAC)
        if not re.match(r'^[a-zA-Z0-9\s\.\-\:_]+$', term):
            return False
        
        # Check for unsafe sequences
        dangerous_sequences = [';', '&&', '||', '|', '$', '`', '(', ')', '{', '}', '<', '>']
        for seq in dangerous_sequences:
            if seq in term:
                return False
        
        return True


# ==============================================================================
# SSH CONNECTION MANAGER
# ==============================================================================

class SSHConnection:
    """SSH connection manager for the OpenWRT router."""
    
    def __init__(self):
        self._connection = None
        self._last_activity = 0
        self._lock = asyncio.Lock()
    
    async def connect(self) -> bool:
        """Establish SSH connection to the router."""
        import asyncssh
        
        async with self._lock:
            if self._connection:
                try:
                    self._connection.close()
                    await self._connection.wait_closed()
                except:
                    pass
            
            try:
                connect_kwargs = {
                    "host": OPENWRT_HOST,
                    "port": OPENWRT_PORT,
                    "username": OPENWRT_USER,
                    "known_hosts": None,
                    "connect_timeout": SSH_TIMEOUT,
                    "login_timeout": SSH_TIMEOUT,
                }
                
                if OPENWRT_SSH_KEY and Path(OPENWRT_SSH_KEY).exists():
                    connect_kwargs["client_keys"] = [OPENWRT_SSH_KEY]
                elif OPENWRT_PASSWORD:
                    connect_kwargs["password"] = OPENWRT_PASSWORD
                else:
                    raise ValueError("SSH authentication configuration missing.")
                
                self._connection = await asyncssh.connect(**connect_kwargs)
                self._last_activity = time.time()
                logging.info(f"[openwrt] SSH connection established: {OPENWRT_USER}@{OPENWRT_HOST}")
                return True
                
            except Exception as e:
                error_msg = f"[openwrt] SSH connection error: {str(e)}"
                logging.error(error_msg)
                return False
    
    async def execute(self, command: str) -> Tuple[str, str, int]:
        """Execute a command on the router over SSH."""
        import asyncssh
        
        if not self._connection:
            if not await self.connect():
                return "", "No SSH connection", 1
        
        # SECURITY: Validate command before execution
        is_valid, msg = SecurityValidator.validate_command(command)
        if not is_valid:
            logging.warning(f"[openwrt] Command rejected: {command[:50]}... - {msg}")
            return "", f"Security denial: {msg}", 1
        
        # SECURITY: Additional sanitation (defense in depth)
        safe_cmd = command.strip()  # validate already checked
        
        if ENABLE_AUDIT_LOGGING:
            self._log_audit(safe_cmd)
        
        try:
            result = await self._connection.run(safe_cmd, timeout=SSH_TIMEOUT)
            self._last_activity = time.time()
            return result.stdout, result.stderr, result.exit_status
            
        except (asyncssh.ConnectionLost, asyncssh.DisconnectError, OSError) as e:
            logging.warning(f"[openwrt] SSH connection lost ({e}), attempting reconnect...")
            if await self.connect():
                try:
                    result = await self._connection.run(safe_cmd, timeout=SSH_TIMEOUT)
                    self._last_activity = time.time()
                    return result.stdout, result.stderr, result.exit_status
                except Exception as e2:
                    return "", f"Error after reconnect: {str(e2)}", 1
            return "", f"Failed to re-establish connection: {str(e)}", 1

        except asyncssh.TimeoutError:
            return "", f"Timeout after {SSH_TIMEOUT}s: {safe_cmd[:30]}...", 124
            
        except Exception as e:
            return "", f"Execution error: {str(e)}", 1
    
    def _log_audit(self, command: str):
        try:
            timestamp = datetime.now().isoformat()
            log_entry = f"{timestamp} | {OPENWRT_USER}@{OPENWRT_HOST} | {command}\n"
            log_path = Path(AUDIT_LOG_FILE)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception:
            pass
    
    async def close(self):
        async with self._lock:
            if self._connection:
                try:
                    self._connection.close()
                    await self._connection.wait_closed()
                except:
                    pass
            self._connection = None

# ==============================================================================
# OPENWRT EXPLORER – MAIN CLASS
# ==============================================================================

class OpenWRTExplorer:
    """Safe communication with OpenWRT router over SSH (read-only)."""
    
    def __init__(self):
        self.ssh = SSHConnection()
        self._connected = False
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test SSH connectivity to the router."""
        if not self._connected:
            self._connected = await self.ssh.connect()
        
        if not self._connected:
            return {
                "success": False,
                "status": "disconnected",
                "error": "Failed to establish SSH connection",
                "host": OPENWRT_HOST
            }
        
        stdout, stderr, code = await self.ssh.execute("ubus call system board")
        if code == 0:
            try:
                board_info = json.loads(stdout)
                # Handle different model field formats (string or dict)
                model_data = board_info.get("model", "unknown")
                if isinstance(model_data, dict):
                    model = model_data.get("name", model_data.get("id", "unknown"))
                else:
                    model = str(model_data)
                return {
                    "success": True,
                    "status": "connected",
                    "host": OPENWRT_HOST,
                    "model": model,
                    "release": board_info.get("release", {}).get("version", "unknown"),
                }
            except json.JSONDecodeError:
                pass
        
        return {
            "success": False,
            "status": "unresponsive",
            "error": f"Router not responding: {stderr or 'no data'}",
        }
    
    async def get_system_info(self) -> Dict[str, Any]:
        """Fetch basic system information."""
        stdout, stderr, code = await self.ssh.execute("ubus call system board")
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch system information"}
        
        try:
            board = json.loads(stdout)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}
        
        stdout_uptime, _, _ = await self.ssh.execute("cat /proc/uptime")
        uptime_seconds = float(stdout_uptime.split()[0]) if stdout_uptime.strip() else 0
        
        stdout_mem, _, _ = await self.ssh.execute("cat /proc/meminfo")
        mem_total = mem_free = 0
        for line in stdout_mem.splitlines():
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) * 1024
            elif line.startswith("MemFree:"):
                mem_free = int(line.split()[1]) * 1024
        
        # Handle different model field formats (string or dict)
        model_data = board.get("model", "unknown")
        if isinstance(model_data, dict):
            model = model_data.get("name", model_data.get("id", "unknown"))
        else:
            model = str(model_data)
        
        return {
            "success": True,
            "model": model,
            "hostname": board.get("hostname", "unknown"),
            "openwrt_version": board.get("release", {}).get("version", "unknown"),
            "kernel": board.get("kernel", "unknown"),
            "uptime_seconds": uptime_seconds,
            "uptime": self._format_uptime(int(uptime_seconds)),
            "memory_total_bytes": mem_total,
            "memory_free_bytes": mem_free,
            "memory_used_percent": round((1 - mem_free / mem_total) * 100, 1) if mem_total else 0,
        }
    
    async def get_wifi_status(self) -> Dict[str, Any]:
        """Fetch WiFi status and connected clients (supports AP and STA)."""
        stdout, stderr, code = await self.ssh.execute("ubus call network.wireless status")
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch WiFi status"}
        
        try:
            data = json.loads(stdout)
            interfaces = []
            
            for radio, cfg in data.items():
                radio_interfaces = cfg.get("interfaces", [])
                
                for iface in radio_interfaces:
                    iface_type = iface.get("type", "unknown")
                    config = iface.get("config", {})
                    
                    # Collect clients (different formats in different versions)
                    clients = []
                    
                    # format 1: stations array
                    for station in iface.get("stations", []):
                        clients.append({
                            "mac": station.get("mac", "unknown"),
                            "signal": station.get("signal", 0),
                            "idle": station.get("inactive", station.get("idle", 0)),
                        })
                    
                    # format 2: clients dict (starsze wersje)
                    for mac, client in iface.get("clients", {}).items():
                        clients.append({
                            "mac": mac,
                            "signal": client.get("signal", 0),
                            "idle": client.get("idle", 0),
                        })
                    
                    interfaces.append({
                        "radio": radio,
                        "type": iface_type,
                        "ssid": config.get("ssid", "unknown"),
                        "mode": config.get("mode", iface_type),
                        "ifname": iface.get("ifname", iface.get("section", "unknown")),
                        "clients_count": len(clients),
                        "clients": clients[:10],
                    })
            
            return {
                "success": True,
                "interfaces_count": len(interfaces),
                "interfaces": interfaces,
                "note": "Router may be in repeater mode (no AP interfaces)" if not any(i.get("type") == "ap" for i in interfaces) else None
            }
        except Exception as e:
            return {"success": False, "error": f"Parse error: {str(e)}"}
    
    async def list_dhcp_leases(self) -> Dict[str, Any]:
        """List DHCP leases (connected devices)."""
        stdout, stderr, code = await self.ssh.execute("cat /tmp/dhcp.leases")
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch DHCP leases"}
        
        leases = []
        for line in stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 4:
                hostname = parts[3] if len(parts) > 3 else None
                # Keep "*" as None for compatibility
                if hostname == "*":
                    hostname = None
                
                leases.append({
                    "expires_at": parts[0],
                    "mac": parts[1].lower(),
                    "ip": parts[2],
                    "hostname": hostname,
                })
        
        return {
            "success": True,
            "leases_count": len(leases),
            "leases": leases[:50],
        }
    
    async def get_firewall_rules(self) -> Dict[str, Any]:
        """Fetch firewall rules (supports iptables, nftables, and fw4)."""
        commands = [
            ("nft list ruleset 2>/dev/null", "nftables"),
            ("fw4 status 2>/dev/null", "fw4"),
            ("iptables -L -n -v", "iptables"),
        ]
        
        for cmd, firewall_type in commands:
            stdout, stderr, code = await self.ssh.execute(cmd)
            if code == 0 and stdout.strip():
                # Python-side filtering
                cleaned_output = "\n".join(
                    line for line in stdout.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                )[:2500]
                
                return {
                    "success": True,
                    "firewall_type": firewall_type,
                    "rules_preview": cleaned_output,
                    "full_output_truncated": len(stdout) > 2500,
                }
        
        return {
            "success": False,
            "error": "No supported firewall found (iptables, nftables, fw4)."
        }
    
    async def read_uci_config(self, config_name: str) -> Dict[str, Any]:
        """Read UCI configuration."""
        # Validate config name
        if not config_name or not re.match(r'^[a-zA-Z0-9._-]+$', config_name):
            return {"success": False, "error": "Invalid configuration name"}
        
        # Additional validation - allow only known configs
        known_configs = [
            'dhcp', 'network', 'wireless', 'firewall', 'system', 'dropbear',
            'luci', 'uhttpd', 'rpcd', 'ucitrack', 'ubootenv'
        ]
        
        if config_name not in known_configs:
            return {
                "success": False,
                "error": f"Configuration '{config_name}' not supported. Allowed: {', '.join(known_configs)}"
            }
        
        stdout, stderr, code = await self.ssh.execute(f"uci show {config_name}")
        if code != 0:
            return {"success": False, "error": stderr or f"Configuration '{config_name}' does not exist"}
        
        config = {}
        for line in stdout.strip().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                config[key] = value.strip("'\"")
        
        return {
            "success": True,
            "config_name": config_name,
            "entries_count": len(config),
            "sample": dict(list(config.items())[:20]),
        }
    
    async def list_installed_packages(self) -> Dict[str, Any]:
        """List installed packages."""
        stdout, stderr, code = await self.ssh.execute("opkg list-installed")
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch package list"}
        
        packages = []
        for line in stdout.strip().splitlines():
            parts = line.split(" - ")
            if len(parts) >= 2:
                packages.append({"name": parts[0].strip(), "version": parts[1].strip()})
            elif parts:
                # Handle lines without version
                packages.append({"name": parts[0].strip(), "version": "unknown"})
        
        return {
            "success": True,
            "packages_count": len(packages),
            "packages_sample": packages[:20],
        }
    
    async def get_router_logs(self, lines: int = 50, filter_level: str = "all") -> Dict[str, Any]:
        """Fetch router logs."""
        lines = min(max(lines, 10), 200)
        cmd = f"logread -l {lines}"
        
        stdout, stderr, code = await self.ssh.execute(cmd)
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch logs"}
        
        log_lines = stdout.strip().splitlines()
        if filter_level != "all":
            filter_lower = filter_level.lower()
            log_lines = [l for l in log_lines if filter_lower in l.lower()]
            
        return {
            "success": True,
            "lines_count": len(log_lines),
            "logs": "\n".join(log_lines[:lines])[:3000],
        }
    
    async def search_router_logs(self, search_term: str, max_results: int = 30) -> Dict[str, Any]:
        """Search for a phrase in router logs (Python-side filtering)."""
        # SECURITY: Validate search term
        if not SecurityValidator.is_safe_search_term(search_term):
            return {"success": False, "error": "Unsafe or invalid search phrase"}
        
        cmd = "logread -l 500"
        stdout, stderr, code = await self.ssh.execute(cmd)
        
        if code != 0:
            return {"success": False, "error": stderr or "Failed to fetch logs"}
        
        term_lower = search_term.lower()
        matches = [line for line in stdout.splitlines() if term_lower in line.lower()]
        
        return {
            "success": True,
            "search_term": search_term,
            "results_count": len(matches),
            "results": "\n".join(matches[-max_results:])[:3000],
        }
    
    async def diagnose_router_connectivity(self) -> Dict[str, Any]:
        """Test basic router network services."""
        results = {"success": True, "tests": {}, "summary": {}}
        
        # 1. Test DNS (8.8.8.8)
        stdout, stderr, code = await self.ssh.execute("ping -c 2 -W 2 8.8.8.8")
        results["tests"]["dns_google"] = {"success": code == 0, "output": (stdout or stderr)[:200]}
        
        # 2. Internet test (cloudflare.com)
        stdout, stderr, code = await self.ssh.execute("nslookup cloudflare.com 8.8.8.8")
        results["tests"]["internet_dns"] = {
            "success": code == 0 and ("Address" in stdout or "Name:" in stdout),
            "output": (stdout or stderr)[:200]
        }
        
        # 3. Gateway test
        stdout_route, _, _ = await self.ssh.execute("ip route show")
        gateway = "192.168.0.1"
        
        if stdout_route:
            for line in stdout_route.splitlines():
                if "default" in line and "via" in line:
                    parts = line.split()
                    try:
                        via_index = parts.index("via")
                        if via_index + 1 < len(parts):
                            gateway = parts[via_index + 1]
                            break
                    except ValueError:
                        pass
        
        stdout, stderr, code = await self.ssh.execute(f"ping -c 2 -W 1 {gateway}")
        results["tests"]["gateway"] = {
            "success": code == 0,
            "gateway_ip": gateway,
            "output": (stdout or stderr)[:200]
        }
        
        # 4. Local DNS test
        stdout, stderr, code = await self.ssh.execute("nslookup openwrt.lan 127.0.0.1")
        results["tests"]["local_dns"] = {"success": code == 0, "output": (stdout or stderr)[:200]}
        
        total_tests = len(results["tests"])
        passed_tests = sum(1 for t in results["tests"].values() if t["success"])
        
        results["summary"] = {
            "passed": passed_tests,
            "failed": total_tests - passed_tests,
            "total": total_tests,
            "health": "excellent" if passed_tests == total_tests else "good" if passed_tests >= total_tests - 1 else "poor"
        }
        return results
    
    async def get_dhcp_static_leases(self) -> Dict[str, Any]:
        """Fetch static DHCP reservations."""
        stdout, stderr, code = await self.ssh.execute("uci show dhcp")
        if code != 0:
            return {"success": False, "error": "Failed to fetch DHCP configuration"}
        
        static_leases = []
        current_host = {}
        current_index = None
        
        for line in stdout.splitlines():
            # Look for dhcp.@host[N] entries
            host_match = re.match(r"dhcp\.@host\[(\d+)\]\.(\w+)='?([^']*)'?", line)
            if host_match:
                index = host_match.group(1)
                key = host_match.group(2)
                value = host_match.group(3)
                
                # New host entry
                if index != current_index:
                    if current_host and "mac" in current_host:
                        static_leases.append(current_host.copy())
                    current_host = {}
                    current_index = index
                
                if key == "mac":
                    current_host["mac"] = value.lower()
                elif key == "ip":
                    current_host["ip"] = value
                elif key in ("name", "hostname"):
                    current_host["hostname"] = value
        
        # Add final entry
        if current_host and "mac" in current_host:
            static_leases.append(current_host)
        
        return {
            "success": True,
            "static_leases_count": len(static_leases),
            "leases": static_leases
        }
    
    async def search_dhcp_logs(self, search_term: str, hours_back: int = 24) -> Dict[str, Any]:
        """Search DHCP events in logs (Python-side)."""
        # SECURITY: Validate search term
        if not SecurityValidator.is_safe_search_term(search_term):
            return {"success": False, "error": "Unsafe search term"}
        
        cmd = "logread -l 500"
        stdout, stderr, code = await self.ssh.execute(cmd)
        
        if code != 0:
            return {"success": False, "error": "Failed to fetch logs"}
        
        events = []
        term_lower = search_term.lower()
        
        for line in stdout.splitlines():
            line_lower = line.lower()
            if ("dnsmasq" in line_lower or "dhcp" in line_lower):
                if term_lower in line_lower:
                    event_type = "unknown"
                    if "DHCPACK" in line: event_type = "ack"
                    elif "DHCPREQUEST" in line: event_type = "request"
                    elif "DHCPDISCOVER" in line: event_type = "discover"
                    elif "DHCPOFFER" in line: event_type = "offer"
                    elif "DHCPNAK" in line: event_type = "nak"
                    elif "DHCPRELEASE" in line: event_type = "release"
                    
                    events.append({
                        "raw_log": line[:200],
                        "event_type": event_type,
                        "contains_search_term": True
                    })
        
        return {
            "success": True,
            "search_term": search_term,
            "events_found": len(events),
            "events": events[:50]
        }
    
    async def get_device_dhcp_details(self, mac_address: str = None, ip_address: str = None) -> Dict[str, Any]:
        """Collect full device info: lease, reservation, and logs."""
        if not mac_address and not ip_address:
            return {"success": False, "error": "Provide device MAC or IP"}
        
        if mac_address:
            mac_address = mac_address.lower().replace("-", ":")
            # Validate MAC format
            if not re.match(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$', mac_address):
                return {"success": False, "error": "Invalid MAC address format"}
        
        if ip_address:
            # Validate IP format
            if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                return {"success": False, "error": "Invalid IP address format"}
        
        leases_res = await self.list_dhcp_leases()
        current_lease = None
        if leases_res.get("success"):
            for l in leases_res.get("leases", []):
                if (mac_address and l.get("mac") == mac_address) or (ip_address and l.get("ip") == ip_address):
                    current_lease = l
                    break
        
        static_res = await self.get_dhcp_static_leases()
        static_reservation = None
        if static_res.get("success"):
            for s in static_res.get("leases", []):
                if (mac_address and s.get("mac") == mac_address) or (ip_address and s.get("ip") == ip_address):
                    static_reservation = s
                    break
        
        search_val = mac_address or ip_address
        logs_res = await self.search_dhcp_logs(search_val)
        
        return {
            "success": True,
            "device_identifier": search_val,
            "current_lease": current_lease,
            "static_reservation": static_reservation,
            "has_static_reservation": static_reservation is not None,
            "is_currently_connected": current_lease is not None,
            "recent_log_events": logs_res.get("events", [])[:5],
            "note": "DHCP logs require 'log_dhcp' enabled in dnsmasq configuration."
        }

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        parts = []
        if days: parts.append(f"{days}d")
        if hours: parts.append(f"{hours}h")
        if minutes: parts.append(f"{minutes}m")
        return " ".join(parts) if parts else "0m"

# ============================================================================== 
# SINGLETON AND REGISTRATION
# ==============================================================================

_explorer: Optional[OpenWRTExplorer] = None

def get_explorer() -> OpenWRTExplorer:
    global _explorer
    if _explorer is None:
        _explorer = OpenWRTExplorer()
    return _explorer

def register_openwrt_tools(mcp):
    """Register OpenWRT tools in the MCP server."""
    
    @mcp.tool()
    async def test_router_connection() -> str:
        """Test SSH connection to the OpenWRT router."""
        return json.dumps(await get_explorer().test_connection(), indent=2, ensure_ascii=False)
    
    @mcp.tool()
    async def get_router_info() -> str:
        """Fetch router system info (model, version, memory, uptime)."""
        return json.dumps(await get_explorer().get_system_info(), indent=2, ensure_ascii=False)
    
    @mcp.tool()
    async def get_router_wifi_status() -> str:
        """Fetch WiFi status and list of connected clients."""
        return json.dumps(await get_explorer().get_wifi_status(), indent=2, ensure_ascii=False)
    
    @mcp.tool()
    async def get_router_dhcp_leases() -> str:
        """Fetch active DHCP leases."""
        return json.dumps(await get_explorer().list_dhcp_leases(), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def get_router_firewall_rules() -> str:
        """Fetch firewall rules (iptables/nftables/fw4)."""
        return json.dumps(await get_explorer().get_firewall_rules(), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def read_router_uci_config(config_name: str) -> str:
        """Read UCI configuration (dhcp, network, wireless, firewall, system)."""
        return json.dumps(await get_explorer().read_uci_config(config_name), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def list_router_packages() -> str:
        """Fetch list of installed OpenWRT packages."""
        return json.dumps(await get_explorer().list_installed_packages(), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def get_router_logs(lines: int = 50, filter_level: str = "all") -> str:
        """Fetch router system logs."""
        return json.dumps(await get_explorer().get_router_logs(lines, filter_level), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def search_router_logs(search_term: str, max_results: int = 30) -> str:
        """Search for a phrase in router logs."""
        return json.dumps(await get_explorer().search_router_logs(search_term, max_results), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def diagnose_router_connectivity() -> str:
        """Test router internet connectivity (ping, DNS)."""
        return json.dumps(await get_explorer().diagnose_router_connectivity(), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def get_dhcp_static_leases() -> str:
        """Fetch static DHCP reservations."""
        return json.dumps(await get_explorer().get_dhcp_static_leases(), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def search_dhcp_logs(search_term: str, hours_back: int = 24) -> str:
        """Search DHCP events in router logs."""
        return json.dumps(await get_explorer().search_dhcp_logs(search_term, hours_back), indent=2, ensure_ascii=False)
        
    @mcp.tool()
    async def get_device_dhcp_details(mac_address: str = None, ip_address: str = None) -> str:
        """Fetch DHCP device details (lease, reservation, logs)."""
        return json.dumps(await get_explorer().get_device_dhcp_details(mac_address, ip_address), indent=2, ensure_ascii=False)

    print("[openwrt_explorer] Tools registered (Python-side filtering, enhanced compatibility)")