# OpenWRT-MCP Documentation

> Read-only MCP (Model Context Protocol) server for OpenWRT router management and diagnostics.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Configuration](#configuration)
5. [MCP Tools](#mcp-tools)
6. [REST API](#rest-api)
7. [Security](#security)
8. [Testing](#testing)
9. [Development](#development)
10. [Troubleshooting](#troubleshooting)

---

## Overview

OpenWRT-MCP provides secure, read-only SSH access to your OpenWRT router through the Model Context Protocol. AI assistants can query router status, network configuration, WiFi clients, firewall rules, and system logs without any ability to modify the system.

**Key design decisions:**
- **Read-only by design** — All SSH commands are whitelisted; no write operations
- **Command whitelist** — Only explicit read-only patterns allowed
- **Python-side filtering** — Commands validated before SSH execution
- **Standalone** — Single Python process, no external databases

---

## Architecture

```
┌─────────────────┐      ┌──────────────────────┐      ┌─────────────────┐
│  MCP Client     │      │  OpenWRT-MCP         │      │  OpenWRT Router │
│  (LibreChat,    │◄────►│  Port 9094-9096      │◄────►│  (SSH)          │
│   Claude, etc.) │ MCP   │  - Health (9094)     │ SSH  │                 │
│                 │ SSE   │  - MCP SSE (9095)    │      │  Dropbear/      │
│                 │       │  - REST API (9096)   │      │  OpenSSH        │
└─────────────────┘       └──────────────────────┘      └─────────────────┘
```

| Port | Protocol | Purpose |
|------|----------|---------|
| 9094 | HTTP | Health check (`GET /health`) |
| 9095 | SSE | MCP transport (`/sse`, `/messages`) |
| 9096 | HTTP | REST API (`/api/*`) |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- OpenWRT router with SSH enabled
- SSH key pair (Ed25519 recommended)

### 1. Setup SSH Key

Generate a key and copy it to the router:

```bash
ssh-keygen -t ed25519 -f openwrt_id_ed25519 -C "openwrt-mcp"
ssh-copy-id -i openwrt_id_ed25519.pub root@192.168.0.1
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your OPENWRT_HOST and SSH key path
```

### 3. Start

```bash
docker compose up -d
```

### 4. Verify

```bash
curl http://localhost:9094/health
```

---

## Configuration

All configuration via environment variables. See `.env.example` for a complete template.

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENWRT_HOST` | Router IP address or hostname | `192.168.0.1` |
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

---

## MCP Tools

### Connection

| Tool | Description |
|------|-------------|
| `test_router_connection` | Verify SSH connectivity to router |

### System Information

| Tool | Description |
|------|-------------|
| `get_router_info` | System board, memory, uptime, release info |
| `get_router_system_resources` | CPU load, memory usage, top processes |

### Network

| Tool | Description |
|------|-------------|
| `get_router_network_interfaces` | Interface IPs, routes, MAC addresses |
| `get_router_wifi_status` | WiFi radios, SSIDs, encryption, connected clients |
| `get_router_dhcp_leases` | Active DHCP leases with hostnames and MACs |

### Security

| Tool | Description |
|------|-------------|
| `get_router_firewall_rules` | iptables/nftables rules and chains |
| `read_router_uci_config` | UCI configuration sections (firewall, network, dhcp, wireless) |

### Diagnostics

| Tool | Description |
|------|-------------|
| `diagnose_router_connectivity` | Ping and DNS resolution tests |
| `get_router_logs` | Recent system logs (logread) |
| `search_router_logs` | Filtered log search by pattern |

### Packages

| Tool | Description |
|------|-------------|
| `list_router_packages` | Installed OPKG packages |

---

## REST API

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/tools` | List all registered tools |
| POST | `/api/tools/{name}` | Call a tool by name |

### Example: Call a Tool

```bash
curl -X POST http://localhost:9096/api/tools/get_router_info \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

## Security

### Read-Only Design

- **No write operations** — All commands are explicitly whitelisted as read-only
- **No system modifications** — Cannot change configuration, install packages, or reboot
- **No file uploads/downloads** — No SCP/SFTP operations

### Command Whitelist

Only the following command categories are permitted:
- `ubus call` (status/info only)
- `uci show/get` (read-only)
- `cat /proc/*`, `cat /etc/*` (system info)
- `iptables -L`, `nft list ruleset` (firewall rules)
- `logread` (system logs)
- `ping`, `nslookup` (diagnostics)
- `opkg list/ info` (package info)
- `ip addr/route show`, `iwinfo` (network status)

### Blocked Patterns

The following are explicitly rejected even if they match whitelist patterns:
- Shell metacharacters: `;`, `|`, `&`, `$`, `` ` ``, `(`, `)`, `{`, `}`, `<`, `>`
- Dangerous commands: `rm`, `reboot`, `wget`, `curl`, `uci set`, `uci add`, `uci remove`, `opkg install`, `opkg remove`
- Path traversal: `../` in file paths

### SSH Security

- **Key-based authentication** — Password login discouraged
- **RejectPolicy** — Unknown host keys rejected (no AutoAddPolicy)
- **Timeout** — Connections timeout after 30 seconds

### Audit Logging

When enabled, all executed commands are logged with timestamp for accountability:

```
2025-04-23T10:00:00Z | test_router_connection | OK | 0.23s
2025-04-23T10:00:05Z | get_router_info | OK | 0.45s
```

---

## Testing

### Unit Tests

No real router required — all SSH connections are mocked.

```bash
pytest tests/ -v --tb=short
```

### Integration Tests

Requires a real OpenWRT router with SSH key access:

```bash
export OPENWRT_HOST=192.168.0.1
export OPENWRT_SSH_KEY=/path/to/openwrt_id_ed25519
pytest tests/ -v -k integration
```

---

## Development

### Project Structure

```
.
├── server.py              # Main server (MCP + REST API)
├── conftest.py            # Test fixtures and mock data
├── requirements.txt       # Dependencies
├── Dockerfile             # Container image
├── docker-compose.yml     # Quick start
├── .env.example           # Configuration template
├── tools/
│   └── openwrt_explorer.py  # All MCP tools and SSH client
├── tests/
│   └── test_openwrt_explorer.py
└── docs/
    └── README.md          # This documentation
```

### Adding a New Tool

1. Add the tool function in `tools/openwrt_explorer.py`
2. Add `@mcp.tool()` decorator
3. Ensure the command is in `SecurityValidator.ALLOWED_PATTERNS`
4. Add tests in `tests/test_openwrt_explorer.py`

### Tool Pattern

```python
@mcp.tool()
async def my_tool(param: str) -> str:
    """
    Brief description.

    Args:
        param: Description

    Returns:
        JSON string with result
    """
    try:
        result = await ssh.execute("safe-read-only-command")
        return json.dumps({"success": True, "data": result}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)
```

---

## Troubleshooting

### Server won't start

1. Check `OPENWRT_HOST` is set
2. Verify SSH key exists at `OPENWRT_SSH_KEY` path
3. Check Docker logs: `docker logs openwrt-mcp`

### SSH connection fails

1. Verify router IP and SSH port
2. Test manually: `ssh -i <key> root@<host>`
3. Ensure Dropbear or OpenSSH is running on the router
4. Check that the public key is in `/etc/dropbear/authorized_keys`

### Commands return errors

1. Verify the command is in the whitelist
2. Check router has required packages (e.g., `nftables` for `nft list ruleset`)
3. Review audit logs for blocked commands

### MCP client can't connect

1. Verify port 9095 is exposed
2. Check SSE endpoint: `curl http://localhost:9095/sse`
3. Ensure CORS settings match your client origin

---

## License

MIT License — see [LICENSE](../LICENSE) for details.

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request
