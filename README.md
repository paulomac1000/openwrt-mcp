# OpenWRT MCP

A hardened MCP server for observing and diagnosing one configured OpenWRT router.

The active profile exposes **19 read capabilities**. Five historical write or destructive capability names remain in the supported catalog but are intentionally inactive and are not registered as callable MCP tools.

## Security posture

- MCP uses the official Python SDK v2 and stdio transport.
- Legacy two-endpoint HTTP+SSE is removed.
- Configuration is validated and frozen before application composition.
- MCP and the optional loopback REST adapter delegate to one invocation kernel.
- SSH commands use closed grammars and dedicated argument validators.
- Shared SSH use is serialized and timeout overrides are task-local.
- Write execution never reconnects and retries after an ambiguous outcome.
- Write and destructive capabilities fail closed until principal-bound approval, target authorization, and real-router tests exist.
- Model-visible results and audit records are sanitized at their respective boundaries.

See [`docs/openwrt-mcp.md`](docs/openwrt-mcp.md) for architecture and failure behavior and [`docs/migration-assessment.yaml`](docs/migration-assessment.yaml) for adoption evidence and residual risks.

## Supported and active tools

The supported catalog contains 24 stable identifiers. The active MCP catalog contains the following 19 read tools:

- `test_router_connection`
- `get_router_info`
- `get_router_wifi_status`
- `get_router_dhcp_leases`
- `get_router_firewall_rules`
- `read_router_uci_config`
- `list_router_packages`
- `get_router_logs`
- `search_router_logs`
- `diagnose_router_connectivity`
- `get_dhcp_static_leases`
- `search_dhcp_logs`
- `get_device_dhcp_details`
- `get_router_context`
- `describe_router_capabilities`
- `ping_host`
- `traceroute_host`
- `nslookup_host`
- `wifi_scan`

Inactive supported identifiers are `restart_interface`, `reload_network`, `uci_set`, `uci_commit`, and `reboot_device`. They are visible through `describe_router_capabilities` with an explicit inactive reason, but they are not exposed through MCP `tools/list`.

## Deterministic mock mode

Mock mode performs no network I/O and exercises all active capabilities:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
OPENWRT_MOCK_MODE=1 PYTHONPATH=src .venv/bin/python scripts/mock_smoke.py
```

Run the full local gate:

```bash
.venv/bin/python scripts/ci.py
```

The repository includes explicit skipped TODO tests for host-key enrollment, cancellation on a real router, and a future approved write workflow. Their preconditions and owners are recorded in the migration assessment.

## Run against a router

Create an SSH key and enroll it on a non-production router. Record the router host key in a dedicated `known_hosts` file.

```bash
cp .env.example .env
# Set OPENWRT_HOST, OPENWRT_SSH_KEY, and OPENWRT_KNOWN_HOSTS.
set -a; . ./.env; set +a
openwrt-mcp
```

The MCP transport is stdio. Diagnostics are written to stderr; stdout is reserved for protocol messages.

## Optional loopback REST adapter

The REST adapter is disabled by default. Enable it only for a local process boundary:

```bash
ENABLE_REST_API=true \
MCP_REST_AUTH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
openwrt-mcp
```

It binds to `127.0.0.1`, bounds request bodies, rejects invalid JSON, uses restrictive configured origins, and invokes the same kernel as MCP. It is not a remote MCP transport.

## Configuration

All settings are loaded once from environment variables. See [`.env.example`](.env.example). Important settings include:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENWRT_HOST` | `192.168.1.1` | Configured router selector |
| `OPENWRT_PORT` | `22` | SSH port |
| `OPENWRT_USER` | `root` | SSH user |
| `OPENWRT_SSH_KEY` | `/app/keys/openwrt_id_ed25519` | Private key path |
| `OPENWRT_KNOWN_HOSTS` | unset | Host identity database; strongly recommended |
| `SSH_TIMEOUT` | `30` | Per-call default deadline in seconds |
| `MCP_TRANSPORT` | `stdio` | Only accepted MCP transport in this profile |
| `OPENWRT_MOCK_MODE` | `false` | Deterministic no-I/O adapter |
| `ENABLE_REST_API` | `false` | Start the loopback convenience adapter |
| `MCP_REST_AUTH_TOKEN` | unset | Optional local REST bearer token |
| `MCP_MAX_REQUEST_BODY_BYTES` | `65536` | REST request bound |

## Standards lock

Adoption is pinned in [`standards-lock.yaml`](standards-lock.yaml) to `paulomac1000/ai-skills` revision `661ff01a5e70d58d6c94a12545b24647e52063ed`, skill version `1.2.0`, for:

- MCP Server Architect
- AFDS Document Writer
- AGENTS.md Architect
- CI/CD Architect

Links to a mutable `main` branch are not used as acceptance evidence.

## Verification scope

The local gate compiles production and test code, validates the immutable standards lock and governed documentation, executes unit and mock end-to-end tests, and runs all active capabilities against deterministic data.

Hosted CI additionally runs Ruff, mypy, Bandit, branch coverage, builds a wheel, installs and tests that exact wheel through the official MCP client, builds a non-root container from the same wheel, and smokes the exact image. Real-router evidence remains a separate owned task; mock success is not represented as production integration evidence.
