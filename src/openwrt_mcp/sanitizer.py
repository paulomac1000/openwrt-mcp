"""Boundary sanitization for logs, audit records, and model-visible data."""

from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.I), "Bearer <REDACTED>"),
    (re.compile(r"Authorization:\s*.+", re.I), "Authorization: <REDACTED>"),
    (
        re.compile(
            r"\b(password|passwd|psk|secret|token|key|api[_-]?key)\b"
            r"(\s*[=:]\s*)('[^']*'|\"[^\"]*\"|\S+)",
            re.I,
        ),
        r"\1\2<REDACTED>",
    ),
)
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_SECRET_KEY_RE = re.compile(
    r"\b(password|passwd|psk|secret|token|key|api[_-]?key|pre[_-]?shared)\b", re.I
)


def _redact_secrets(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_log_line(line: str) -> str:
    return _IP_PATTERN.sub("<IP_REDACTED>", _redact_secrets(line))


def sanitize_response_data(data: Any) -> Any:
    if isinstance(data, str):
        return _redact_secrets(data)
    if isinstance(data, dict):
        sanitized: dict[Any, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                sanitized[key] = "<REDACTED>"
            else:
                sanitized[key] = sanitize_response_data(value)
        return sanitized
    if isinstance(data, list):
        return [sanitize_response_data(item) for item in data]
    if isinstance(data, tuple):
        return tuple(sanitize_response_data(item) for item in data)
    return data
