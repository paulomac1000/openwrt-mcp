"""Serialized SSH client with per-invocation options and fail-closed writes."""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from openwrt_mcp.observability import get_caller_context, get_request_id
from openwrt_mcp.sanitizer import sanitize_log_line
from openwrt_mcp.settings import Settings, get_settings
from openwrt_mcp.validators import SecurityValidator

logger = logging.getLogger("openwrt-mcp.ssh")
_CLOSE_TIMEOUT_SECONDS = 2.0


class SSHConnection:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._connection: Any = None
        self._connect_lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._cancel_requested: contextvars.ContextVar[bool] = contextvars.ContextVar(
            f"ssh_cancel_{id(self)}",
            default=False,
        )
        self._timeout_override: contextvars.ContextVar[int | None] = contextvars.ContextVar(
            f"ssh_timeout_{id(self)}",
            default=None,
        )

    def set_timeout(self, seconds: int) -> None:
        """Set a task-local timeout for compatibility with internal callers."""
        if not 1 <= seconds <= 300:
            raise ValueError("timeout must be between 1 and 300 seconds")
        self._timeout_override.set(seconds)

    @contextmanager
    def timeout_scope(self, seconds: int) -> Iterator[None]:
        if not 1 <= seconds <= 300:
            raise ValueError("timeout must be between 1 and 300 seconds")
        token = self._timeout_override.set(seconds)
        try:
            yield
        finally:
            self._timeout_override.reset(token)

    def cancel(self) -> None:
        """Request cancellation in the current task context.

        Cross-task cancellation must use ``Task.cancel()``.
        """
        self._cancel_requested.set(True)

    async def connect(self) -> bool:
        import asyncssh

        async with self._connect_lock:
            if self._connection is not None:
                is_closed = getattr(self._connection, "is_closed", None)
                if not callable(is_closed) or not is_closed():
                    return True
                self._connection = None

            if self.settings.openwrt_known_hosts is not None:
                known_hosts: str | None = str(self.settings.openwrt_known_hosts)
            elif self.settings.insecure_skip_host_key_check:
                logger.warning("SSH host-key verification is explicitly disabled")
                known_hosts = None
            else:
                logger.error("OPENWRT_KNOWN_HOSTS is required")
                return False

            kwargs: dict[str, Any] = {
                "host": self.settings.openwrt_host,
                "port": self.settings.openwrt_port,
                "username": self.settings.openwrt_user,
                "known_hosts": known_hosts,
                "connect_timeout": self.settings.ssh_timeout,
                "login_timeout": self.settings.ssh_timeout,
            }
            if self.settings.openwrt_ssh_key.exists():
                kwargs["client_keys"] = [str(self.settings.openwrt_ssh_key)]
            elif self.settings.openwrt_password:
                kwargs["password"] = self.settings.openwrt_password
            else:
                logger.error("SSH authentication configuration missing")
                return False

            try:
                self._connection = await asyncssh.connect(**kwargs)
                return True
            except Exception as exc:
                logger.error("SSH connection failed (%s)", type(exc).__name__)
                self._connection = None
                return False

    async def execute(
        self,
        command: str,
        *,
        timeout_seconds: int | None = None,
    ) -> tuple[str, str, int]:
        valid, message = SecurityValidator.validate_command(command)
        if not valid:
            return "", f"Security denial: {message}", 1
        return await self._execute_once(
            command.strip(),
            timeout_seconds=timeout_seconds,
            write_operation=False,
        )

    async def execute_write(
        self,
        command: str,
        *,
        timeout_seconds: int | None = None,
    ) -> tuple[str, str, int]:
        valid, message = SecurityValidator.validate_write_command(command)
        if not valid:
            return "", f"Security denial: {message}", 1
        if self.settings.openwrt_known_hosts is None:
            return (
                "",
                "Security denial: write operations require OPENWRT_KNOWN_HOSTS",
                1,
            )
        return await self._execute_once(
            command.strip(),
            timeout_seconds=timeout_seconds,
            write_operation=True,
        )

    async def _discard_connection(self) -> None:
        """Detach and close the current SSH session after an ambiguous interruption."""
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
            await asyncio.wait_for(
                connection.wait_closed(),
                timeout=_CLOSE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            abort = getattr(connection, "abort", None)
            if callable(abort):
                abort()
            logger.warning("SSH connection cleanup timed out")
        except Exception as exc:
            logger.warning("SSH connection cleanup failed (%s)", type(exc).__name__)

    async def _execute_once(
        self,
        command: str,
        *,
        timeout_seconds: int | None,
        write_operation: bool,
    ) -> tuple[str, str, int]:
        import asyncssh

        timeout = timeout_seconds
        if timeout is None:
            timeout = self._timeout_override.get()
        if timeout is None:
            timeout = self.settings.ssh_timeout
        if not 1 <= timeout <= 300:
            return "", "Invalid timeout", 1
        if self._cancel_requested.get():
            self._cancel_requested.set(False)
            return "", "Operation cancelled", 130

        async with self._command_lock:
            if self._connection is None and not await self.connect():
                return "", "No SSH connection", 1
            if self.settings.enable_audit_logging:
                self._log_audit(command)
            try:
                result = await self._connection.run(command, timeout=timeout)
                return (
                    str(result.stdout),
                    str(result.stderr),
                    int(result.exit_status),
                )
            except asyncio.CancelledError:
                await self._discard_connection()
                raise
            except TimeoutError:
                await self._discard_connection()
                return "", f"Timeout after {timeout}s", 124
            except (
                asyncssh.ConnectionLost,
                asyncssh.DisconnectError,
                OSError,
            ):
                await self._discard_connection()
                if write_operation:
                    return (
                        "",
                        "AMBIGUOUS_OUTCOME: SSH connection lost during write",
                        125,
                    )
                return (
                    "",
                    "SSH connection lost during read; command was not replayed",
                    125,
                )
            except Exception as exc:
                logger.error("SSH command execution failed (%s)", type(exc).__name__)
                return "", "SSH command execution failed", 1

    def _log_audit(self, command: str) -> None:
        caller = get_caller_context()
        entry = (
            f"{datetime.now(UTC).isoformat()} | {get_request_id()} | "
            f"caller={caller.principal} | "
            f"target={self.settings.openwrt_user}@{self.settings.openwrt_host} | "
            f"{command}\n"
        )
        try:
            path = self.settings.audit_log_file
            path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags | nofollow, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(sanitize_log_line(entry))
        except OSError as exc:
            logger.error("Audit log write failed (%s)", type(exc).__name__)

    async def close(self) -> None:
        async with self._connect_lock:
            await self._discard_connection()
