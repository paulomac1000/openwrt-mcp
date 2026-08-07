"""Transport-independent invocation kernel and capability registry."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from openwrt_mcp.observability import build_meta, request_context
from openwrt_mcp.sanitizer import sanitize_response_data
from openwrt_mcp.validators import ValidationError

Operation = Callable[..., Awaitable[dict[str, Any]]]
_MISSING = object()


@dataclass(frozen=True, slots=True)
class InputField:
    """One transport-independent capability input field."""

    types: tuple[type[Any], ...]
    required: bool = False
    default: Any = _MISSING
    minimum: int | float | None = None
    maximum: int | float | None = None
    max_length: int | None = None

    def validate(self, name: str, value: Any) -> Any:
        if int in self.types and isinstance(value, bool):
            raise ValidationError(f"{name} must be an integer")
        if not isinstance(value, self.types):
            expected = " or ".join(item.__name__ for item in self.types)
            raise ValidationError(f"{name} must be {expected}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.minimum is not None and value < self.minimum:
                raise ValidationError(f"{name} must be at least {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise ValidationError(f"{name} must be at most {self.maximum}")
        if isinstance(value, str) and self.max_length is not None:
            if len(value) > self.max_length:
                raise ValidationError(
                    f"{name} must contain at most {self.max_length} characters"
                )
        return value

    def as_json_schema(self) -> dict[str, Any]:
        primitive = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            type(None): "null",
        }
        type_names = [primitive[item] for item in self.types if item in primitive]
        schema: dict[str, Any]
        if len(type_names) == 1:
            schema = {"type": type_names[0]}
        else:
            schema = {"type": type_names}
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        if self.default is not _MISSING:
            schema["default"] = self.default
        return schema


@dataclass(frozen=True, slots=True)
class InputSchema:
    """Closed capability input contract shared by every transport."""

    fields: Mapping[str, InputField] = field(default_factory=dict)

    def validate(self, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValidationError("tool arguments must be a JSON object")
        unknown = sorted(set(arguments) - set(self.fields))
        if unknown:
            raise ValidationError(f"Unknown argument(s): {', '.join(unknown)}")

        normalized: dict[str, Any] = {}
        for name, definition in self.fields.items():
            if name in arguments:
                normalized[name] = definition.validate(name, arguments[name])
            elif definition.default is not _MISSING:
                normalized[name] = copy.deepcopy(definition.default)
            elif definition.required:
                raise ValidationError(f"Missing required argument: {name}")
        return normalized

    def as_json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                name: definition.as_json_schema()
                for name, definition in self.fields.items()
            },
            "required": [
                name for name, definition in self.fields.items() if definition.required
            ],
            "additionalProperties": False,
        }


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    name: str
    version: str
    risk: str
    side_effects: str
    confidentiality: str
    operational_impact: str
    cost: str
    idempotent: bool
    retryable: bool
    concurrent_safe: bool
    timeout_ms: int
    requires_confirmation: bool
    reversible: bool
    max_response_bytes: int = 262_144
    active: bool = True
    inactive_reason: str | None = None
    concurrency_group: str | None = None
    input_schema: InputSchema = field(default_factory=InputSchema)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "risk": self.risk,
            "side_effects": self.side_effects,
            "confidentiality": self.confidentiality,
            "operational_impact": self.operational_impact,
            "cost": self.cost,
            "idempotent": self.idempotent,
            "retryable": self.retryable,
            "concurrent_safe": self.concurrent_safe,
            "timeout_ms": self.timeout_ms,
            "requires_confirmation": self.requires_confirmation,
            "reversible": self.reversible,
            "max_response_bytes": self.max_response_bytes,
            "active": self.active,
            "inactive_reason": self.inactive_reason,
            "concurrency_group": self.concurrency_group,
            "input_schema": self.input_schema.as_json_schema(),
        }


@dataclass(frozen=True, slots=True)
class KernelError:
    code: str
    message: str
    retryable: bool = False
    suggestion: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.suggestion:
            value["suggestion"] = self.suggestion
        return value


@dataclass(frozen=True, slots=True)
class KernelResult:
    success: bool
    data: Any = None
    error: KernelError | None = None
    meta: dict[str, Any] | None = None

    @classmethod
    def ok(cls, data: Any, *, meta: dict[str, Any]) -> "KernelResult":
        return cls(success=True, data=sanitize_response_data(data), meta=meta)

    @classmethod
    def failed(
        cls,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        suggestion: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> "KernelResult":
        return cls(
            success=False,
            error=KernelError(
                code=code,
                message=str(sanitize_response_data(message)),
                retryable=retryable,
                suggestion=(
                    str(sanitize_response_data(suggestion))
                    if suggestion is not None
                    else None
                ),
            ),
            meta=meta,
        )

    def as_dict(self) -> dict[str, Any]:
        if self.success:
            payload: dict[str, Any] = {"success": True, "data": self.data}
        else:
            payload = {
                "success": False,
                "error": (self.error or KernelError("INTERNAL", "Unknown error")).as_dict(),
            }
        if self.meta is not None:
            payload["_meta"] = self.meta
        return payload


class CapabilityRegistry:
    def __init__(self, manifests: dict[str, CapabilityManifest]) -> None:
        self._manifests = dict(manifests)

    def get(self, name: str) -> CapabilityManifest:
        try:
            return self._manifests[name]
        except KeyError as exc:
            raise ValidationError(f"Unknown capability: {name}") from exc

    def supported(self) -> list[dict[str, Any]]:
        return [self._manifests[name].as_dict() for name in sorted(self._manifests)]

    def active(self) -> list[dict[str, Any]]:
        return [item for item in self.supported() if item["active"]]

    def active_names(self) -> tuple[str, ...]:
        return tuple(item["name"] for item in self.active())


class InvocationKernel:
    """One governed execution path for all capability invocations."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        operations: dict[str, Operation],
        target_identity: str,
    ) -> None:
        self.registry = registry
        self._operations = dict(operations)
        self._target_identity = target_identity
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        active = set(registry.active_names())
        missing = active - self._operations.keys()
        orphaned = self._operations.keys() - active
        if missing or orphaned:
            raise ValueError(
                f"capability registration mismatch: missing={sorted(missing)}, "
                f"orphaned={sorted(orphaned)}"
            )

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(key, asyncio.Lock())

    def _meta(
        self,
        name: str,
        started: float,
        manifest: CapabilityManifest,
    ) -> dict[str, Any]:
        return {
            **build_meta(
                name,
                started,
                retry_safe=manifest.retryable and manifest.idempotent,
            ),
            "target": self._target_identity,
        }

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> KernelResult:
        started = time.monotonic()
        try:
            manifest = self.registry.get(name)
        except ValidationError as exc:
            return KernelResult.failed("NOT_FOUND", str(exc))

        with request_context(request_id):
            if not manifest.active:
                return KernelResult.failed(
                    "CAPABILITY_INACTIVE",
                    manifest.inactive_reason or "Capability is inactive",
                    meta=self._meta(name, started, manifest),
                )
            operation = self._operations.get(name)
            if operation is None:
                return KernelResult.failed(
                    "REGISTRATION_ERROR",
                    "No operation registered for active capability",
                    meta=self._meta(name, started, manifest),
                )
            try:
                normalized = manifest.input_schema.validate(arguments)
            except ValidationError as exc:
                return KernelResult.failed(
                    "INVALID_PARAM",
                    str(exc),
                    meta=self._meta(name, started, manifest),
                )

            deadline_seconds = max(0.001, manifest.timeout_ms / 1000)
            lock: asyncio.Lock | None = None
            if not manifest.concurrent_safe:
                group = manifest.concurrency_group or "target"
                lock = await self._lock_for(f"{self._target_identity}:{group}")

            try:
                async with asyncio.timeout(deadline_seconds):
                    if lock is None:
                        result = await operation(**normalized)
                    else:
                        async with lock:
                            result = await operation(**normalized)
                meta = self._meta(name, started, manifest)
                if isinstance(result, dict) and result.get("success") is False:
                    error = result.get("error")
                    if isinstance(error, dict):
                        return KernelResult.failed(
                            str(error.get("code", "UPSTREAM_FAILURE")),
                            str(error.get("message", "Operation failed")),
                            retryable=bool(
                                error.get("retryable", False) and manifest.retryable
                            ),
                            suggestion=error.get("suggestion"),
                            meta=meta,
                        )
                    return KernelResult.failed(
                        "UPSTREAM_FAILURE",
                        str(error or "Operation failed"),
                        meta=meta,
                    )
                candidate = KernelResult.ok(result, meta=meta)
                try:
                    response_size = len(
                        json.dumps(
                            candidate.as_dict(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                    )
                except (TypeError, ValueError):
                    return KernelResult.failed(
                        "INTERNAL",
                        "Operation returned a non-serializable response",
                        meta=meta,
                    )
                if response_size > manifest.max_response_bytes:
                    return KernelResult.failed(
                        "RESPONSE_TOO_LARGE",
                        "Operation response exceeded its declared byte limit",
                        meta=meta,
                    )
                return candidate
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                return KernelResult.failed(
                    "TIMEOUT",
                    f"{name} exceeded its declared deadline",
                    retryable=manifest.retryable,
                    meta=self._meta(name, started, manifest),
                )
            except (ValidationError, TypeError, ValueError) as exc:
                return KernelResult.failed(
                    "INVALID_PARAM",
                    str(exc),
                    meta=self._meta(name, started, manifest),
                )
            except Exception:
                return KernelResult.failed(
                    "INTERNAL",
                    "Internal server error",
                    meta=self._meta(name, started, manifest),
                )


def decode_kernel_response(result: KernelResult) -> tuple[int, dict[str, Any]]:
    """Map a governed result to a conventional HTTP status for future adapters."""
    if result.success:
        return 200, result.as_dict()
    code = (result.error or KernelError("INTERNAL", "Unknown error")).code
    status = {
        "INVALID_PARAM": 400,
        "AUTHENTICATION_REQUIRED": 401,
        "AUTHORIZATION_DENIED": 403,
        "NOT_FOUND": 404,
        "CAPABILITY_INACTIVE": 409,
        "TIMEOUT": 504,
        "UPSTREAM_FAILURE": 502,
        "RESPONSE_TOO_LARGE": 502,
    }.get(code, 500)
    return status, result.as_dict()
