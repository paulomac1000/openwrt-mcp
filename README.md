# OpenWRT-MCP

Read-only MCP (Model Context Protocol) server for OpenWRT router management and diagnostics.
Enables AI assistants to observe and analyze an OpenWRT router without any write access.

## Architecture

| Port | Purpose |
|------|---------|
| 9094 | Health check (`GET /health`) |
| 9095 | MCP SSE transport (`/sse`, `/messages`) |
| 9096 | REST API (`/api/*`) |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- OpenWRT router with SSH enabled (Dropbear or OpenSSH)
- SSH key pair for authentication

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

### 3. Start

```bash
docker compose up -d
```

### 4. Verify

```bash
curl http://localhost:9094/health
```

## Configuration

All configuration via environment variables. See `.env.example`.

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
| `ENABLE_AUDIT_LOGGING` | `true` | Log all executed commands |

## Tools

12+ read-only MCP tools covering:

| Tool | Description |
|------|-------------|
| `test_router_connection` | Verify SSH connectivity |
| `get_router_info` | System board info, memory, uptime |
| `get_router_wifi_status` | WiFi radios, SSIDs, connected clients |
| `get_router_dhcp_leases` | Active DHCP leases |
| `get_router_firewall_rules` | iptables/nftables rules |
| `read_router_uci_config` | UCI configuration sections |
| `list_router_packages` | Installed OPKG packages |
| `get_router_logs` | Recent system logs |
| `search_router_logs` | Filtered log search |
| `diagnose_router_connectivity` | Ping and DNS tests |
| `get_router_network_interfaces` | Interface status and IP addresses |
| `get_router_system_resources` | CPU load, memory usage, processes |

## Security

- **SSH key authentication only** — Password login not recommended
- **Command whitelist** — Only read-only commands allowed
- **Blocked patterns** — `rm`, `reboot`, `wget`, `uci set/add/remove`, shell metacharacters
- **RejectPolicy for unknown hosts** — No automatic host key acceptance
- **Audit logging** — All commands logged with timestamps

## Testing

```bash
# Unit tests (no router required — all mocked)
pytest tests/ -v --tb=short
```

## Docker

```bash
docker build -t openwrt-mcp .
docker run -d \
  -p 9094:9094 -p 9095:9095 -p 9096:9096 \
  -e OPENWRT_HOST=192.168.0.1 \
  -e OPENWRT_SSH_KEY=/app/keys/openwrt_id_ed25519 \
  -v ./keys:/app/keys:ro \
  openwrt-mcp
```

## License

MIT
