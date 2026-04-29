# OpenWRT-MCP

[![CI](https://github.com/paulomac1000/openwrt-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/paulomac1000/openwrt-mcp/actions/workflows/ci.yml)
[![Docker](https://github.com/paulomac1000/openwrt-mcp/actions/workflows/publish.yml/badge.svg)](https://github.com/paulomac1000/openwrt-mcp/actions/workflows/publish.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Read-only MCP (Model Context Protocol) server for OpenWRT router management and diagnostics. Enables AI assistants (Claude Desktop, LibreChat, Cline) to observe and analyze an OpenWRT router without any write access.

## Requirements

- Python 3.11+ (for local use) or Docker
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
cp .env.example .env
# edit .env with your OPENWRT_HOST and OPENWRT_SSH_KEY
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
  -v ./keys:/app/keys:ro \
  ghcr.io/paulomac1000/openwrt-mcp:latest
```

**Building locally:**

```bash
docker build -t openwrt-mcp .
docker run -d \
  -p 9094:9094 -p 9095:9095 -p 9096:9096 \
  -e OPENWRT_HOST=192.168.0.1 \
  -e OPENWRT_SSH_KEY=/app/keys/openwrt_id_ed25519 \
  -v ./keys:/app/keys:ro \
  openwrt-mcp
```

### 4. Run locally (Python 3.11+)

```bash
pip install -r requirements.txt
OPENWRT_HOST=192.168.0.1 OPENWRT_SSH_KEY=/path/to/key python server.py
```

## Ports

| Port | Protocol | Purpose | Endpoint |
|------|----------|---------|----------|
| 9094 | HTTP | Health check | `GET /health` |
| 9095 | SSE | MCP transport | `/sse`, `/messages` |
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
```

## Available Tools (12+)

All tools are **read-only** — no configuration changes, no reboots, no package installations.

| Category | Tools |
|----------|-------|
| **Connection** | `test_router_connection` |
| **System** | `get_router_info` — board, memory, uptime, release |
| **Network** | `get_router_wifi_status`, `get_router_dhcp_leases`, `diagnose_router_connectivity` |
| **Security** | `get_router_firewall_rules`, `read_router_uci_config` |
| **Diagnostics** | `get_router_logs`, `search_router_logs` |
| **Packages** | `list_router_packages` |
| **DHCP** | `get_dhcp_static_leases`, `search_dhcp_logs`, `get_device_dhcp_details` |

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
| `OPENWRT_PASSWORD` | — | Password (not recommended; use keys) |
| `MCP_SSE_PORT` | `9095` | MCP SSE transport port |
| `REST_API_PORT` | `9096` | REST API port |
| `SSH_TIMEOUT` | `30` | SSH connection timeout (seconds) |
| `ENABLE_AUDIT_LOGGING` | `true` | Log all executed commands |
| `AUDIT_LOG_FILE` | `/var/log/openwrt_mcp.log` | Audit log path |

## Security Model

- **Read-only by design** — All SSH commands are whitelisted; no write operations allowed
- **Command whitelist** — Only explicit read-only patterns permitted (`ubus call`, `uci show`, `cat /proc/*`, `logread`, `ping`, etc.)
- **Blocked patterns** — `rm`, `reboot`, `wget`, `curl`, `uci set/add/remove`, shell metacharacters (`;`, `|`, `&&`, `$`, etc.)
- **Key-based authentication** — Password login discouraged
- **Audit logging** — All commands logged with timestamps for accountability

## Testing

```bash
# Unit tests (no router required — all mocked)
pytest tests/unit/ -v --tb=short
```

## Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "openwrt": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:9095/sse"]
    }
  }
}
```

## License

MIT
