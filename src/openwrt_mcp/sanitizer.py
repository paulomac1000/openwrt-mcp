"""Boundary sanitization for logs, audit records, and model-visible data."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.I), "Bearer <REDACTED>"),
    (re.compile(r"Authorization:\s*.+", re.I), "Authorization: <REDACTED>"),
    (
        re.compile(
            r"(?<![A-Za-z0-9])"
            r"(?P<name>password|passwd|psk|secret|token|key|api[_-]?key|pre[_-]?shared)"
            r"(?![A-Za-z0-9])"
            r"(?P<separator>\s*[=:]\s*)"
            r"(?P<value>'[^']*'|\"[^\"]*\"|\S+)",
            re.I,
        ),
        r"\g<name>\g<separator><REDACTED>",
    ),
)
_IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_CANDIDATE_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])"
)
_MAC_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])",
    re.I,
)
_SECRET_KEY_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])"
    r"(?:password|passwd|psk|secret|token|key|api[_-]?key|pre[_-]?shared)"
    r"(?:$|[^A-Za-z0-9])",
    re.I,
)


def _redact_secrets(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_ipv6(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        try:
            parsed = ipaddress.ip_address(candidate)
        except ValueError:
            return candidate
        return "<IP_REDACTED>" if parsed.version == 6 else candidate

    return _IPV6_CANDIDATE_PATTERN.sub(replace, text)


def sanitize_log_line(line: str) -> str:
    sanitized = _redact_secrets(line)
    sanitized = _IPV4_PATTERN.sub("<IP_REDACTED>", sanitized)
    sanitized = _redact_ipv6(sanitized)
    return _MAC_PATTERN.sub("<MAC_REDACTED>", sanitized)


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
