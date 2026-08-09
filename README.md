# OpenWRT MCP

Hardened read-only MCP server for observing one OpenWRT router over SSH.

## Supported runtime profile

This is intentionally an **L1 local read-only stdio** profile. It does not claim L2 authentication, principal authorization, or stable target binding.

- CPython `3.12.x` on a POSIX host
- Official MCP Python SDK `2.0.0`
- MCP stdio transport only
- 19 active read capabilities
- 5 historical write/destructive capability names retained as inactive metadata
- Optional loopback-only HTTP liveness/readiness endpoint on port 9094
- Verified SSH host identity required outside mock mode
- L1 caller identity derived from `os.geteuid()`; non-POSIX startup fails closed

REST and legacy HTTP+SSE are intentionally not part of this profile. This avoids sharing `asyncio` locks and an AsyncSSH connection between independent event loops or threads.

The current breaking migration is versioned as **2.0.0** because the public transport, SDK, runtime, tool catalog, timeout ownership, and response semantics differ materially from the last published 1.x line.

## Configure the router

```bash
ssh-keygen -t ed25519 -f keys/openwrt_id_ed25519 -C openwrt-mcp
ssh-copy-id -i keys/openwrt_id_ed25519.pub root@192.168.1.1
ssh-keyscan -H 192.168.1.1 > keys/known_hosts
cp .env.example .env
```

Set at least `OPENWRT_HOST`, `OPENWRT_SSH_KEY`, and `OPENWRT_KNOWN_HOSTS`. Real-mode startup fails immediately when the configured `known_hosts` file does not exist or neither a usable SSH key nor password is available.

## Local development

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python scripts/ci.py
```

For deterministic development without a router:

```bash
OPENWRT_MOCK_MODE=1 .venv/bin/python scripts/mock_smoke.py
```

## Run

The server communicates over stdin/stdout. Diagnostics are written to stderr.

```bash
OPENWRT_HOST=192.168.1.1 \
OPENWRT_SSH_KEY=$PWD/keys/openwrt_id_ed25519 \
OPENWRT_KNOWN_HOSTS=$PWD/keys/known_hosts \
openwrt-mcp
```

The health listener is optional and binds only to `127.0.0.1:9094` when enabled:

```bash
HEALTH_ENABLED=1 openwrt-mcp
curl http://127.0.0.1:9094/live
curl http://127.0.0.1:9094/ready
```

For stdio clients which do not need an HTTP health port, set `HEALTH_ENABLED=0`. This prevents an unrelated local port collision from blocking MCP startup.

## Docker

CI builds the wheel first, builds the image exactly once from that wheel plus the reviewed hashed runtime lockfile, smoke-tests that exact image, and exports it for later promotion. The image runs as UID 10001, uses `SIGINT` for graceful Docker stop, and includes a loopback `/live` health check.

```bash
python -m build --wheel --no-isolation
docker build -t openwrt-mcp:local .
```

Run the container under an MCP host that attaches to its stdio. Mount the private key and known-hosts file read-only. For hardened deployments, also use a read-only root filesystem, drop Linux capabilities, set `no-new-privileges`, and provide writable storage only for `/tmp` and the audit-log location if audit logging is enabled.

## Capability and input policy

Every capability has a closed input schema owned by the invocation kernel. The kernel rejects missing fields, unknown fields, invalid types, and out-of-range values before acquiring the target lock or performing SSH I/O. The MCP adapter publishes that exact kernel schema, including length and numeric limits; SDK-generated wrapper metadata is checked for field/required parity before registration completes. Deadlines are server-owned and are not public tool parameters.

All non-concurrent-safe operations are serialized for the complete router target unless a narrower concurrency group is explicitly reviewed. Cancellation, timeout, connection loss, or a remote-output overflow invalidates the current SSH session before a later request may reconnect; commands are never automatically replayed after an ambiguous disconnect. Raw SSH stdout and stderr share a 1 MiB capture budget enforced while bytes are read, before decoding or MCP response serialization.

Version 2 also makes partial/negative data explicit. Failed `/proc` reads no longer become fake zero uptime/memory values, failed DHCP sources no longer become false "not connected"/"no reservation" claims, and failed ping/traceroute/nslookup commands no longer report successful tool execution. Aggregate responses expose partial state where useful.

## Production acceptance

Ordinary CI proves deterministic behavior, official MCP compatibility, static/security gates, exact-wheel behavior, and exact-container behavior. The remaining environment-dependent gate is the real-router laboratory suite:

```bash
OPENWRT_LAB_RUN=1 \
OPENWRT_LAB_SLOW_TARGET=198.51.100.254 \
OPENWRT_LAB_WIFI_RADIO=wlan0 \
.venv/bin/python -m pytest -vv -m lab \
  tests/integration/test_real_router_acceptance.py
```

The lab must report **6 passed, 0 failed, 0 skipped** for the intended router/firmware environment. In addition to host-key, cancellation, timeout, and response-limit checks, the suite now invokes **all 19 advertised read tools** through the official MCP client. Routers whose interface names or DNS setup differ should set the documented `OPENWRT_LAB_*` overrides in `docs/production-acceptance.md`; do not weaken assertions or skip an advertised tool.

Do not claim “production verified against real OpenWRT” for the current candidate until that six-test record is retained for the exact final revision. See `docs/production-acceptance.md` for prerequisites and evidence handling. The single write-profile `NOT_IMPLEMENTED` placeholder is deliberately outside the supported read-only L1 profile.

## Release evidence

The publish workflow does not check out source or rebuild dependencies/image. It consumes the closed image archive produced and smoke-tested by a successful CI run for the exact `main` SHA, verifies its checksum and source label, and publishes only the immutable SHA tag with provenance attestation.

See `docs/openwrt-mcp.md`, `docs/production-acceptance.md`, and `docs/migration-assessment.yaml` for architecture, acceptance, and standards status.
