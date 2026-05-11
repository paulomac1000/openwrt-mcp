---
description: Complete reference for OpenWRT-MCP server covering architecture, configuration, MCP tools, REST API, security design, testing, and deployment
doc_id: ref.openwrt-mcp
type: ref
status: active
rigor_tier: L2
ttl_days: 180
stability: stable
ai_scope: editable
domain: mcp
tags: ["openwrt", "mcp", "router", "ssh", "read-only"]
upstream:
  - ref.documentation-standard
source_of_truth: true
last_verified: 2026-05-11
owners: ["backend-team"]
---

# OpenWRT-MCP Reference

## PURPOSE

Provide secure, read-only SSH access to an OpenWRT router through the
Model Context Protocol. Enables AI assistants to query router status,
network configuration, WiFi clients, firewall rules, and system logs
without any ability to modify the system.

Key design decisions:
- Read-only by design — all SSH commands are whitelisted, no write
  operations
- Command whitelist — only explicit read-only patterns allowed
- Python-side command validation before SSH execution
- Standalone single Python process, no external databases

## SCOPE

- INCLUDED: MCP server architecture, port assignments, 13 MCP tool
  catalog, REST API endpoints, SSH security whitelist, configuration
  environment variables, test suite structure, Docker deployment,
  build system, CI pipeline
- EXCLUDED: MCP protocol specification, client-side tool calling,
  CI infrastructure configuration, OpenWRT router firmware
  configuration, network topology outside the router

## DEFINITIONS

- `MCP Server`: A FastMCP-based process exposing read-only OpenWRT
  tools over SSE transport
- `OpenWRT Router`: Target device running OpenWRT with SSH enabled
- `SecurityValidator`: Whitelist-based command filter preventing
  command injection
- `REST API`: HTTP endpoints on port 9096 for health checks, tool
  listing, and tool invocation
- `SSH Connection`: asyncssh-based connection manager with
  auto-reconnect, timeout handling, and audit logging
- `UCI`: Unified Configuration Interface — system configuration
  framework on OpenWRT
- `ubus`: OpenWRT micro bus IPC for service communication
- `FastMCP`: Python framework for building MCP servers
- `SSE`: Server-Sent Events — transport protocol for MCP

## RULES

1. System MUST validate all SSH commands through
   `SecurityValidator.validate_command()` before execution
2. System MUST block shell metacharacters: ; | & $ ` ( ) { } < > \0
3. System MUST block destructive commands: rm, reboot, halt, poweroff,
   wget, curl, dd, mkfs, mv, chmod, chown
4. System MUST block UCI write operations: uci set, add, remove,
   delete, rename, revert, commit
5. System MUST block package modifications: opkg install, remove,
   upgrade, update, configure
6. System MUST block pipe-to-shell patterns: | sh, | bash, | ash
7. System MUST use try/except Exception in every tool wrapper
8. System MUST return structured JSON with `"success"` boolean from
   every tool
9. System MUST return `_meta` envelope with `request_id`, `duration_ms`,
   and `tool_version` for observed tools
10. System MUST log only to stderr — stdout corrupts MCP transport
11. System MUST default to 127.0.0.1 binding for all ports
12. System MUST require `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1` to
    bind to 0.0.0.0 on public access

## INTERFACES

### Ports

| Port | Protocol | Purpose | Endpoints |
|------|----------|---------|-----------|
| 9094 | HTTP | Health check | `GET /health` |
| 9095 | SSE | MCP transport | `/sse`, `/messages` |
| 9096 | HTTP | REST API wrapper | `/api/*` |

### Health Endpoint

- INPUT: None
- OUTPUT: JSON with status, tools_registered, tool_invocations,
  version, endpoints map

### REST API

- `GET /api/health` — system health and metrics
- `GET /api/tools` — list all registered tools with descriptions
- `POST /api/tools/{tool_name}` — invoke a tool by name
- `GET /api/tools/{tool_name}/manifest` — tool capability manifest

### MCP Tools

All 13 tools are exposed as MCP-tool functions via SSE transport.
Each tool is registered with FastMCP and wrapped in try/except.

| Tool | Description | Parameters |
|------|-------------|------------|
| `test_router_connection` | Verify SSH connectivity to router | None |
| `get_router_info` | System board, memory, uptime, release | None |
| `get_router_wifi_status` | WiFi radios, SSIDs, connected clients | None |
| `get_router_dhcp_leases` | Active DHCP leases with hostnames, MACs | None |
| `get_router_firewall_rules` | iptables/nftables/fw4 firewall rules | None |
| `read_router_uci_config` | UCI configuration sections | `config_name` |
| `list_router_packages` | Installed OPKG packages | None |
| `get_router_logs` | Recent system logs from logread | `lines`, `filter_level` |
| `search_router_logs` | Filtered log search by pattern | `search_term`, `max_results`, `timeout_seconds` |
| `diagnose_router_connectivity` | Ping and DNS resolution tests | `timeout_seconds` |
| `get_dhcp_static_leases` | Static DHCP reservations from UCI | None |
| `search_dhcp_logs` | Search DHCP events in logs | `search_term`, `hours_back`, `timeout_seconds` |
| `get_device_dhcp_details` | Full device info: lease, reservation, logs | `mac_address`, `ip_address` |

### Tool Response Format

Success:
```json
{"success": true, "data": <any>, "_meta": {"request_id": "...", "duration_ms": 42, "tool_version": "1.1.0", "cached": false, "retry_safe": true}}
```

Error:
```json
{"success": false, "error": "message"}
```

Extended error (L2+):
```json
{"success": false, "error": {"code": "INVALID_PARAM", "message": "...", "retryable": false, "suggestion": "..."}}
```

## STATE

### Project Structure

```
src/openwrt_mcp/
  server.py               # Entry point, REST API, health endpoint
  validators.py           # SecurityValidator, ValidationError
  observability.py        # request_id, _meta envelope, per-tool counters
  tools/
    constants.py          # SSOT for all environment variable defaults
    ssh_client.py         # SSH connection manager, async
    explorer.py           # OpenWRTExplorer — all internal functions
    response_helpers.py   # _success_response, _error_response helpers
    registration.py       # register_openwrt_tools — 13 MCP tool wrappers
  __main__.py              # python -m entry point
tests/
  unit/                   # 115 unit tests (all mocked, no I/O)
  integration/            # 22 integration tests (in-process MCP)
  smoke/                  # 8 smoke tests (REST API health checks)
  e2e/                    # 9 E2E tests (full pipeline)
```

### Environment Variables

Required:
| Variable | Default | Description |
|----------|---------|-------------|
| OPENWRT_HOST | 192.168.1.1 | Router IP address |
| OPENWRT_SSH_KEY | /app/keys/openwrt_id_ed25519 | Path to SSH private key |

Optional:
| Variable | Default | Description |
|----------|---------|-------------|
| OPENWRT_PORT | 22 | SSH port |
| OPENWRT_USER | root | SSH username |
| OPENWRT_PASSWORD | None | Password (not recommended) |
| SSH_TIMEOUT | 30 | SSH connection timeout (seconds) |
| MCP_SSE_PORT | 9095 | MCP SSE transport port |
| REST_API_PORT | 9096 | REST API port |
| LOG_LEVEL | INFO | Logging level |
| ENABLE_AUDIT_LOGGING | true | Log all executed commands |
| AUDIT_LOG_FILE | /var/log/openwrt_mcp.log | Audit log file path |
| MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED | (unset) | Set to `1` to bind to `0.0.0.0` (required for Docker) |

### Assumptions

- Target router runs OpenWRT with Dropbear or OpenSSH enabled
- SSH key-based authentication is configured on the router
- Server runs as a single Python process with daemon threads for
  health and REST API
- Python 3.13 or newer is available (3.13-slim base Docker image)

### Constraints

- Maximum 13 registered MCP tools (fixed at implementation time)
- Single-router connection only (no multi-router support)
- No write operations — strictly read-only
- SSH timeout is configurable but bounded (default 30s)

### Known Limitations

- No multi-router support — one server instance serves one router
- No configuration changes — read-only by design
- No package installations or upgrades
- DHCP logs require `log_dhcp` option enabled in dnsmasq config
- Audit log file grows unbounded — rotation is operator responsibility

## EDGE_CASES

- CASE: Router SSH is unreachable
  EXPECTED: Tool returns `{"success": false, "error": "..."}` with
  status "disconnected". Server continues operating for retry.
- CASE: SSH key file not found at startup
  EXPECTED: Server logs warning, tools return connection errors on
  invocation. Server does not crash.
- CASE: Invalid config name passed to read_router_uci_config
  EXPECTED: Returns `INVALID_PARAM` error with list of valid config
  names and suggestion.
- CASE: Invalid MAC or IP format in get_device_dhcp_details
  EXPECTED: Returns `INVALID_PARAM` error with format suggestion.
- CASE: Client disconnects during long-running tool (diagnose)
  EXPECTED: SSE transport detects disconnect. Tool continues in
  background; result is discarded.
- CASE: All backend connections fail at startup
  EXPECTED: Server starts, tools return connection errors.
- CASE: Banned search term passed to search_router_logs
  EXPECTED: Returns `INVALID_PARAM` error before any SSH call.
- CASE: MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED is not set
  EXPECTED: Server binds to 127.0.0.1 (localhost only).

## EXAMPLES

### Health Check

```bash
curl http://localhost:9094/health
```

Response:
```json
{"status": "healthy", "tools_registered": 13, "version": "1.1.0"}
```

### List Tools

```bash
curl http://localhost:9096/api/tools
```

### Call a Tool via REST API

```bash
curl -X POST http://localhost:9096/api/tools/get_router_info \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Call a Tool with Parameters

```bash
curl -X POST http://localhost:9096/api/tools/read_router_uci_config \
  -H "Content-Type: application/json" \
  -d '{"config_name": "dhcp"}'
```

### Get Tool Manifest

```bash
curl http://localhost:9096/api/tools/get_router_info/manifest
```

### Tool Manifest Response

```json
{
  "name": "get_router_info",
  "version": "1.1.0",
  "risk": "READ",
  "side_effects": "read",
  "idempotent": true,
  "retryable": true,
  "concurrent_safe": false,
  "timeout_ms": 15000,
  "requires_confirmation": false,
  "determinism": "env-dependent",
  "latency": "moderate",
  "cost": "cheap"
}
```

### Docker Run

```bash
docker run -d \
  --name openwrt-mcp \
  -p 9094:9094 -p 9095:9095 -p 9096:9096 \
  -e OPENWRT_HOST=192.168.0.1 \
  -e OPENWRT_SSH_KEY=/app/keys/openwrt_id_ed25519 \
  -v ./keys:/app/keys:ro \
  ghcr.io/paulomac1000/openwrt-mcp:latest
```

### Build and Verify Docker Image

```bash
docker build -t openwrt-mcp .
docker run --rm openwrt-mcp python -c \
  "from openwrt_mcp.server import get_tool_count; print(get_tool_count())"
```

### Run Unit Tests

```bash
pytest tests/unit/ -v --tb=short
```

### Run All Tests with Coverage

```bash
pytest tests/ --cov=openwrt_mcp --cov-fail-under=80 -v
```

## NON_GOALS

- Does not specify MCP wire protocol internals
- Does not define CI/CD pipeline configuration
- Does not cover OpenWRT router firmware configuration
- Does not provide multi-router or multi-device support
- Does not define client-side MCP tool calling patterns
- Does not replace OpenWRT vendor documentation
- Does not handle credential rotation or key management
- Does not define log retention or rotation policy

## CHANGELOG

### [1.0.0] — 2026-05-11
- Initial release with 13 read-only MCP tools
- Extended error responses with structured codes
- Tool manifests with capability descriptors
- Per-tool observability (request_id, _meta, counters)
- CI pipeline with ruff, mypy, bandit, coverage (80%)
- Smoke and E2E test suites
