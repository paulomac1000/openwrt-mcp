"""Secret sanitization for log output and response payloads.

Two trust boundaries, two functions:

* ``sanitize_log_line()``  — runs on every log record (Canonical Template 4a).
  Redacts credentials AND IP addresses: log files SHOULD NOT leak LAN
  topology or secrets.
* ``sanitize_response_data()`` — runs on the payload returned to the agent
  inside ``_success_response()`` (Canonical Template 4b). Redacts credentials
  only. IP and MAC addresses are PRESERVED on purpose: reporting DHCP leases,
  connectivity tests, and routing data is this server's core function, so
  redacting addresses here would make most tools useless. WiFi pre-shared
  keys (``uci show wireless`` exposes ``key='...'``) remain the real secret
  and ARE redacted.
"""

import re
from typing import Any

# Credential / key patterns — redacted in BOTH logs and response payloads.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), "Bearer <REDACTED>"),
    (re.compile(r"Authorization:\s*.+", re.IGNORECASE), "Authorization: <REDACTED>"),
    # key='psk', password=..., token: ... — quoted or bare value.
    (
        re.compile(
            r"\b(password|passwd|psk|secret|token|key|api[_-]?key)\b(\s*[=:]\s*)"
            r"('[^']*'|\"[^\"]*\"|\S+)",
            re.IGNORECASE,
        ),
        r"\1\2<REDACTED>",
    ),
]

# IP addresses — redacted in logs ONLY (see module docstring).
_IP_PATTERN: tuple[re.Pattern[str], str] = (
    re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "<IP_REDACTED>",
)

# Dict keys whose value is a secret — caught even when config is returned as
# structured data (e.g. {"key": "psk"}) rather than a flat `uci show` line.
_SECRET_KEY_RE: re.Pattern[str] = re.compile(
    r"\b(password|passwd|psk|secret|token|key|api[_-]?key|pre[_-]?shared)\b",
    re.IGNORECASE,
)


def _redact_secrets(text: str) -> str:
    """Replace credentials, tokens, and keys in a string."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_log_line(line: str) -> str:
    """Redact credentials and IP addresses from a single log line."""
    line = _redact_secrets(line)
    pattern, replacement = _IP_PATTERN
    return pattern.sub(replacement, line)


def sanitize_response_data(data: Any) -> Any:
    """Recursively redact credentials from a response structure.

    IP and MAC addresses are intentionally preserved — see module docstring.
    Applied at the ``_success_response()`` boundary so a tool that forgets to
    sanitize cannot leak a secret.
    """
    if isinstance(data, str):
        return _redact_secrets(data)
    if isinstance(data, dict):
        result: dict[Any, Any] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str) and v and _SECRET_KEY_RE.search(k):
                result[k] = "<REDACTED>"
            else:
                result[k] = sanitize_response_data(v)
        return result
    if isinstance(data, list):
        return [sanitize_response_data(item) for item in data]
    if isinstance(data, tuple):
        return tuple(sanitize_response_data(item) for item in data)
    return data
