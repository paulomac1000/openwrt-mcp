"""Serialized SSH client with per-invocation options and fail-closed writes."""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from openwrt_mcp.observability import get_request_id
from openwrt_mcp.sanitizer import sanitize_log_line
from openwrt_mcp.settings import Settings, get_settings
from openwrt_mcp.validators import SecurityValidator

logger = logging.getLogger("openwrt-mcp.ssh")


class SSHConnection:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._connection: Any = None
        self._connect_lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._cancel_requested: contextvars.ContextVar[bool] = contextvars.ContextVar(
            f"ssh_cancel_{id(self)}", default=False
        )
        self._timeout_override: contextvars.ContextVar[int | None] = contextvars.ContextVar(
            f"ssh_timeout_{id(self)}", default=None
        )

    def set_timeout(self, seconds: int) -> None:
        """Set a task-local timeout for legacy wrappers.

        The value is isolated by ``ContextVar`` and therefore cannot leak across
        overlapping asyncio tasks. New code should use ``timeout_scope``.
        """
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

        Cross-task cancellation must use ``Task.cancel()``; this compatibility
        method is intentionally context-local to prevent one request cancelling
        another request.
        """
        self._cancel_requested.set(True)

    async def connect(self) -> bool:
        import asyncssh

        async with self._connect_lock:
            if self._connection is not None:
                return True

            kwargs: dict[str, Any] = {
                "host": self.settings.openwrt_host,
                "port": self.settings.openwrt_port,
                "username": self.settings.openwrt_user,
                "known_hosts": str(self.settings.openwrt_known_hosts)
                if self.settings.openwrt_known_hosts
                else None,
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
                logger.error("SSH connection failed: %s", exc)
                self._connection = None
                return False

    async def execute(
        self, command: str, *, timeout_seconds: int | None = None
    ) -> tuple[str, str, int]:
        valid, message = SecurityValidator.validate_command(command)
        if not valid:
            return "", f"Security denial: {message}", 1
        return await self._execute_once(
            command.strip(), timeout_seconds=timeout_seconds, allow_reconnect=True
        )

    async def execute_write(
        self, command: str, *, timeout_seconds: int | None = None
    ) -> tuple[str, str, int]:
        valid, message = SecurityValidator.validate_write_command(command)
        if not valid:
            return "", f"Security denial: {message}", 1
        if self.settings.openwrt_known_hosts is None:
            return "", "Security denial: write operations require OPENWRT_KNOWN_HOSTS", 1
        return await self._execute_once(
            command.strip(), timeout_seconds=timeout_seconds, allow_reconnect=False
        )

    async def _execute_once(
        self,
        command: str,
        *,
        timeout_seconds: int | None,
        allow_reconnect: bool,
    ) -> tuple[str, str, int]:
        import asyncssh

        timeout = timeout_seconds or self._timeout_override.get() or self.settings.ssh_timeout
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
                return str(result.stdout), str(result.stderr), int(result.exit_status)
            except asyncio.CancelledError:
                raise
            except (asyncssh.ConnectionLost, asyncssh.DisconnectError, OSError) as exc:
                self._connection = None
                if not allow_reconnect:
                    return "", f"AMBIGUOUS_OUTCOME: connection lost during write: {exc}", 125
                if await self.connect():
                    try:
                        result = await self._connection.run(command, timeout=timeout)
                        return str(result.stdout), str(result.stderr), int(result.exit_status)
                    except Exception as retry_exc:
                        return "", f"Read failed after reconnect: {retry_exc}", 1
                return "", f"Connection lost: {exc}", 1
            except TimeoutError:
                return "", f"Timeout after {timeout}s", 124
            except Exception as exc:
                return "", f"Execution error: {exc}", 1

    def _log_audit(self, command: str) -> None:
        entry = (
            f"{datetime.now(UTC).isoformat()} | {get_request_id()} | "
            f"{self.settings.openwrt_user}@{self.settings.openwrt_host} | {command}\n"
        )
        try:
            path = self.settings.audit_log_file
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(sanitize_log_line(entry))
        except OSError as exc:
            logger.error("Audit log write failed: %s", exc)

    async def close(self) -> None:
        async with self._connect_lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                try:
                    connection.close()
                    await connection.wait_closed()
                except Exception as exc:
                    logger.warning("SSH close failed: %s", exc)
