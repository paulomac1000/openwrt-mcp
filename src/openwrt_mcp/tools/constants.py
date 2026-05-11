"""Centralized constants — Single Source of Truth for all environment variables."""

import os

OPENWRT_HOST = os.getenv("OPENWRT_HOST", "192.168.1.1")
OPENWRT_PORT = int(os.getenv("OPENWRT_PORT", "22"))
OPENWRT_USER = os.getenv("OPENWRT_USER", "root")
OPENWRT_SSH_KEY = os.getenv("OPENWRT_SSH_KEY", "/app/keys/openwrt_id_ed25519")
OPENWRT_PASSWORD = os.getenv("OPENWRT_PASSWORD", None)
SSH_TIMEOUT = int(os.getenv("SSH_TIMEOUT", "30"))
ENABLE_AUDIT_LOGGING = os.getenv("ENABLE_AUDIT_LOGGING", "true").lower() in (
    "1",
    "true",
    "yes",
)
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "/var/log/openwrt_mcp.log")

MCP_SSE_PORT = int(os.getenv("MCP_SSE_PORT", "9095"))
REST_API_PORT = int(os.getenv("REST_API_PORT", "9096"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
