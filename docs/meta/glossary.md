---
description: Central glossary of domain terms used across project documentation
doc_id: ref.glossary
type: ref
status: active
rigor_tier: L0
ttl_days: 180
stability: stable
ai_scope: editable
source_of_truth: true
last_verified: 2026-05-11
owners: ["backend-team"]
---

# Glossary

- `MCP`: Model Context Protocol — protocol for communication between
  AI agents and tools/servers
- `SSE`: Server-Sent Events — MCP transport over long-lived HTTP
  connection
- `OpenWRT`: Linux distribution for routers based on Buildroot
- `UCI`: Unified Configuration Interface — configuration framework
  on OpenWRT
- `ubus`: OpenWRT micro bus IPC for communicating with system
  services
- `DHCP`: Dynamic Host Configuration Protocol — automatic IP
  address assignment
- `SSH`: Secure Shell — encrypted remote access protocol
- `FastMCP`: Python framework for building MCP servers
- `asyncssh`: Asynchronous SSH library for Python
- `SecurityValidator`: Whitelist-based command filter preventing
  SSH command injection
- `ValidationError`: Exception class for input validation failures
- `REST API`: HTTP-based API on port 9096 exposing MCP tools
- `Docker`: Container runtime for deploying the MCP server
- `ruff`: Python linter and formatter used in CI
- `mypy`: Static type checker used in CI
- `bandit`: Security linter used in CI
