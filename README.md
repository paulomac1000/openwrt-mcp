# OpenWRT-MCP

[![CI](https://github.com/paulomac1000/openwrt-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/paulomac1000/openwrt-mcp/actions/workflows/ci.yml)
[![Docker](https://github.com/paulomac1000/openwrt-mcp/actions/workflows/publish.yml/badge.svg)](https://github.com/paulomac1000/openwrt-mcp/actions/workflows/publish.yml)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Read-only MCP (Model Context Protocol) server for OpenWRT router management and diagnostics.
Enables AI assistants (Claude Desktop, LibreChat, Cline) to observe and analyze an OpenWRT
router without any write access.

## Requirements

- Python 3.14+ (for local use) or Docker
- OpenWRT router with SSH enabled (Dropbear or OpenSSH)
- SSH key pair for authentication

## Quick Start

### 1. Generate SSH Key

```bash
ssh-keygen -t ed25519 -f openwrt_id_ed25519 -C "openwrt-mcp"
ssh-copy-id -i openwrt_id_ed25519.pub root@192.168.0.1
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your OPENWRT_HOST and SSH key path
```

### 3. Run with Docker

**Option A — with docker compose:**

```bash
# After editing .env, for Docker add MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1 to .env
docker compose up -d
```

**Option B — with plain docker run:**

```bash
docker run -d \
  --name openwrt-mcp \
  -p 9094:9094 \
  -p 9095:9095 \
  -p 9096:9096 \
  -e OPENWRT_HOST=192.168.0.1 \
  -e OPENWRT_SSH_KEY=/app/keys/openwrt_id_ed25519 \
  -e MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1 \
  -v $(pwd)/keys:/app/keys:ro \
  ghcr.io/paulomac1000/openwrt-mcp:latest
```

**Building locally:**

```bash
git clone https://github.com/paulomac1000/openwrt-mcp.git
cd openwrt-mcp
docker build -t openwrt-mcp .
# Then run with the same docker run command above
```

### 4. Run locally (Python 3.14+)

```bash
pip install -e ".[dev]"
OPENWRT_HOST=192.168.0.1 OPENWRT_SSH_KEY=/path/to/key openwrt-mcp
```

## Ports

| Port | Protocol | Purpose | Endpoint |
|------|----------|---------|----------|
| 9094 | HTTP | Health check | `GET /health` |
| 9095 | SSE | MCP transport (SSE) | `/sse`, `/messages` |
| 9096 | HTTP | REST API | `/api/*` |

### Verify

```bash
# Health check
curl http://localhost:9094/health

# List all MCP tools
curl http://localhost:9096/api/tools

# Call a tool
curl -X POST http://localhost:9096/api/tools/get_router_info \
  -H "Content-Type: application/json" \
  -d '{}'

# Get tool manifest
curl http://localhost:9096/api/tools/get_router_info/manifest
```

## Available Tools (24)

Tools are categorized by risk level: **[READ]** tools are safe — they query the router with no side effects.
**[WRITE]** tools can modify router state and require `ENABLE_WRITE_OPERATIONS=1` in `.env`.
**[DESTRUCTIVE]** tools are irreversible (reboot) and require explicit confirmation.

| Category | Tool | Risk | Description |
|----------|------|------|-------------|
| **Connection** | `test_router_connection` | READ | Verify SSH connectivity |
| **System** | `get_router_info` | READ | Board info, memory, uptime, release |
| | `get_router_context` | READ | Unified context snapshot (system, wifi, DHCP, health) |
| | `describe_router_capabilities` | READ | Server introspection — tools, manifests, collectors |
| **Network** | `get_router_wifi_status` | READ | WiFi radios, SSIDs, connected clients |
| | `get_router_dhcp_leases` | READ | Active DHCP leases |
| | `diagnose_router_connectivity` | READ | Ping, DNS, and gateway tests |
| | `ping_host` | READ | Ping a specific host |
| | `traceroute_host` | READ | Traceroute to a host |
| | `nslookup_host` | READ | DNS lookup from the router |
| | `wifi_scan` | READ | Scan neighboring WiFi networks |
| **Security** | `get_router_firewall_rules` | READ | iptables / nftables / fw4 rules |
| | `read_router_uci_config` | READ | Read UCI configuration sections |
| **Diagnostics** | `get_router_logs` | READ | Recent system logs |
| | `search_router_logs` | READ | Filtered log search |
| **Packages** | `list_router_packages` | READ | Installed OPKG packages |
| **DHCP** | `get_dhcp_static_leases` | READ | Static DHCP reservations |
| | `search_dhcp_logs` | READ | Search DHCP events in logs |
| | `get_device_dhcp_details` | READ | Full device info (lease, reservation, logs) |
| **Write** | `uci_set` | WRITE | Set a UCI configuration value |
| | `uci_commit` | WRITE | Commit UCI changes permanently |
| | `restart_interface` | WRITE | Restart a network interface |
| | `reload_network` | WRITE | Reload network services |
| | `reboot_device` | DESTRUCTIVE | Reboot the router (irreversible) |

## Configuration

All configuration is via environment variables. See `.env.example` for a complete template.

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENWRT_HOST` | Router IP address | `192.168.0.1` |
| `OPENWRT_SSH_KEY` | Path to SSH private key | `/app/keys/openwrt_id_ed25519` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENWRT_PORT` | `22` | SSH port |
| `OPENWRT_USER` | `root` | SSH username |
| `MCP_SSE_PORT` | `9095` | MCP SSE transport port |
| `REST_API_PORT` | `9096` | REST API port |
| `SSH_TIMEOUT` | `30` | SSH connection timeout (seconds) |
| `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED` | — | Set to `1` for Docker port forwarding |
| `ENABLE_WRITE_OPERATIONS` | `false` | Set to `1` to enable write tools (uci_set, reboot, etc.) |
| `OPENWRT_PASSWORD` | `None` | SSH password (not recommended — use SSH keys) |
| `ENABLE_AUDIT_LOGGING` | `true` | Log all executed commands |
| `AUDIT_LOG_FILE` | `/var/log/openwrt_mcp.log` | Audit log path |
| `LOG_LEVEL` | `INFO` | Logging level |

## Security Model

- **Read-only by default** — All SSH commands are whitelisted; write operations (`uci set`, `ifdown`, `ubus reboot`) require `ENABLE_WRITE_OPERATIONS=1`
- **Command whitelist** — Explicit read-only patterns (`ubus call`, `uci show`, `cat /proc/*`, `logread`, `ping`, etc.)
- **Write command whitelist** — Separate `execute_write()` path for write operations (`ifdown`, `ifup`, `uci set/commit`, `/etc/init.d/network`, `ubus reboot`)
- **Blocked patterns** — `rm`, `reboot`, `wget`, `curl`, `uci set` (in read path), shell metacharacters (`;`, `|`, `&&`, `$`, etc.)
- **Key-based authentication** — Password login discouraged
- **Audit logging** — All commands logged with timestamps for accountability
- **Localhost binding** — All ports bind to `127.0.0.1` by default; set `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1` for Docker

## Standards Compliance

This server follows two AI-First standards:

| Standard | Document | Version | Description |
|----------|----------|---------|-------------|
| **AFDS** | [`docs_standards.md`](https://github.com/paulomac1000/ai-skills/blob/main/skills/afds-doc-writer/docs_standards.md) | v1.0 | Documentation structure, frontmatter schema, controlled language |
| **MCP Core** | [`mcp-server-standards.md`](https://github.com/paulomac1000/ai-skills/blob/main/skills/mcp-server-architect/mcp-server-standards.md) | v1.1.0 | Tool design, response contracts, testing hierarchy, security |

Compliance level: **L3-ready** (all L1-L3 rules met; Risk Consistency Matrix enforced by automated tests).

## Testing

```bash
pip install -e ".[dev]"
pytest tests/unit/ tests/integration/ -q       # 268 tests (requires .env for integration)
pytest tests/unit/ --cov=openwrt_mcp -q         # 80%+ coverage
ruff check . && ruff format --check .           # lint
mypy src/openwrt_mcp/ --strict                  # type check
bandit -r src/openwrt_mcp/ -ll                  # security
```

## Quick Reference

| Metric | Value |
|--------|-------|
| Python | 3.14+ (Docker: 3.14) |
| Tools | 24 (19 READ + 4 WRITE + 1 DESTRUCTIVE) |
| Tests | 296 (215 unit + 53 integration + 10 smoke + 18 e2e) |
| Coverage | 86% |
| Lint | 0 errors (ruff + mypy --strict + bandit) |
| Docker | `ghcr.io/paulomac1000/openwrt-mcp:latest` |
| Standards | AFDS v1.0 + [MCP Core v1.1.0](https://github.com/paulomac1000/ai-skills) — L2+ |
| License | MIT |

## License

MIT
