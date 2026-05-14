"""SSH connection manager for the OpenWRT router."""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from openwrt_mcp.observability import get_request_id
from openwrt_mcp.tools.constants import (
    AUDIT_LOG_FILE,
    ENABLE_AUDIT_LOGGING,
    OPENWRT_HOST,
    OPENWRT_PASSWORD,
    OPENWRT_PORT,
    OPENWRT_SSH_KEY,
    OPENWRT_USER,
    SSH_TIMEOUT,
)
from openwrt_mcp.validators import SecurityValidator


class SSHConnection:
    """SSH connection manager for the OpenWRT router."""

    def __init__(self) -> None:
        self._connection: Any = None
        self._last_activity: float = 0.0
        self._lock = asyncio.Lock()
        self._timeout: int = SSH_TIMEOUT
        self._cancelled = asyncio.Event()

    def set_timeout(self, seconds: int) -> None:
        """Override SSH timeout for the next command."""
        self._timeout = seconds

    def cancel(self) -> None:
        """Signal cancellation to in-flight operations."""
        self._cancelled.set()

    async def connect(self) -> bool:
        """Establish SSH connection to the router."""
        import asyncssh

        self._cancelled.clear()
        async with self._lock:
            if self._connection:
                try:
                    self._connection.close()
                    await self._connection.wait_closed()
                except Exception:
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
                logging.info(
                    f"[{get_request_id()}] [openwrt] SSH connection established:"
                    f" {OPENWRT_USER}@{OPENWRT_HOST}"
                )
                return True

            except Exception as e:
                error_msg = f"[{get_request_id()}] [openwrt] SSH connection error: {str(e)}"
                logging.error(error_msg)
                return False

    async def execute(self, command: str) -> tuple[str, str, int]:
        """Execute a command on the router over SSH."""
        import asyncssh

        if not self._connection:
            if not await self.connect():
                return "", "No SSH connection", 1

        # SECURITY: Validate command before execution
        is_valid, msg = SecurityValidator.validate_command(command)
        if not is_valid:
            logging.warning(
                f"[{get_request_id()}] [openwrt] Command rejected: {command[:50]}... - {msg}"
            )
            return "", f"Security denial: {msg}", 1

        # SECURITY: Additional sanitation (defense in depth)
        safe_cmd = command.strip()

        if self._cancelled.is_set():
            return "", "Operation cancelled", 1

        if ENABLE_AUDIT_LOGGING:
            self._log_audit(safe_cmd)

        timeout = self._timeout

        try:
            result = await self._connection.run(safe_cmd, timeout=timeout)
            self._last_activity = time.time()
            return result.stdout, result.stderr, result.exit_status

        except (asyncssh.ConnectionLost, asyncssh.DisconnectError, OSError) as e:
            logging.warning(
                f"[{get_request_id()}] [openwrt] SSH connection lost ({e}), attempting reconnect..."
            )
            if await self.connect():
                try:
                    result = await self._connection.run(safe_cmd, timeout=timeout)
                    self._last_activity = time.time()
                    return result.stdout, result.stderr, result.exit_status
                except Exception as e2:
                    return "", f"Error after reconnect: {str(e2)}", 1
            return "", f"Failed to re-establish connection: {str(e)}", 1

        except asyncssh.TimeoutError:
            return "", f"Timeout after {timeout}s: {safe_cmd[:30]}...", 124

        except Exception as e:
            return "", f"Execution error: {str(e)}", 1

        finally:
            self._timeout = SSH_TIMEOUT  # always reset to default

    async def execute_write(self, command: str) -> tuple[str, str, int]:
        """Execute a write operation on the router over SSH.

        Uses ALLOWED_WRITE_PATTERNS instead of ALLOWED_PATTERNS for validation.
        Only used by write tools (restart_interface, uci_set, etc.).
        """
        import asyncssh

        if not self._connection:
            if not await self.connect():
                return "", "No SSH connection", 1

        is_valid, msg = SecurityValidator.validate_write_command(command)
        if not is_valid:
            logging.warning(
                f"[{get_request_id()}] [openwrt] Write command rejected: {command[:50]}... - {msg}"
            )
            return "", f"Security denial: {msg}", 1

        safe_cmd = command.strip()
        if self._cancelled.is_set():
            return "", "Operation cancelled", 1
        if ENABLE_AUDIT_LOGGING:
            self._log_audit(safe_cmd)
        timeout = self._timeout
        try:
            result = await self._connection.run(safe_cmd, timeout=timeout)
            self._last_activity = time.time()
            return result.stdout, result.stderr, result.exit_status
        except (asyncssh.ConnectionLost, asyncssh.DisconnectError, OSError) as e:
            logging.warning(
                f"[{get_request_id()}] [openwrt] SSH connection lost during write ({e}),"
                " attempting reconnect..."
            )
            if await self.connect():
                try:
                    result = await self._connection.run(safe_cmd, timeout=timeout)
                    self._last_activity = time.time()
                    return result.stdout, result.stderr, result.exit_status
                except Exception as retry_err:
                    return "", str(retry_err), 1
            return "", str(e), 1
        except asyncssh.TimeoutError:
            return "", f"Timeout after {timeout}s: {safe_cmd[:30]}...", 124
        except Exception as e:
            return "", f"Execution error: {str(e)}", 1
        finally:
            self._timeout = SSH_TIMEOUT

    def _log_audit(self, command: str) -> None:
        try:
            timestamp = datetime.now().isoformat()
            log_entry = f"{timestamp} | {OPENWRT_USER}@{OPENWRT_HOST} | {command}\n"
            log_path = Path(AUDIT_LOG_FILE)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception:
            pass

    async def close(self) -> None:
        async with self._lock:
            if self._connection:
                try:
                    self._connection.close()
                    await self._connection.wait_closed()
                except Exception:
                    pass
            self._connection = None
