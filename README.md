# OpenWRT MCP

Hardened read-only MCP server for observing one OpenWRT router over SSH.

## Supported runtime profile

This is intentionally an **L1 local read-only stdio** profile. It does not claim L2 authentication, principal authorization, or stable target binding.

- Official MCP Python SDK `2.0.0`
- MCP stdio transport only
- 19 active read capabilities
- 5 historical write/destructive capability names retained as inactive metadata
- Loopback-only HTTP liveness/readiness endpoint on port 9094
- Verified SSH host identity required outside mock mode

REST and legacy HTTP+SSE are intentionally not part of this profile. This avoids sharing `asyncio` locks and an AsyncSSH connection between independent event loops or threads.

## Configure the router

```bash
ssh-keygen -t ed25519 -f keys/openwrt_id_ed25519 -C openwrt-mcp
ssh-copy-id -i keys/openwrt_id_ed25519.pub root@192.168.1.1
ssh-keyscan -H 192.168.1.1 > keys/known_hosts
cp .env.example .env
```

Set at least `OPENWRT_HOST`, `OPENWRT_SSH_KEY`, and `OPENWRT_KNOWN_HOSTS`.

## Local development

```bash
python3 -m venv .venv
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

The optional health listener binds to `127.0.0.1:9094`:

```bash
curl http://127.0.0.1:9094/live
curl http://127.0.0.1:9094/ready
```

## Docker

CI builds the wheel first, builds the image exactly once from that wheel plus the reviewed hashed runtime lockfile, smoke-tests that exact image, and exports it for later promotion.

```bash
python -m build --wheel --no-isolation
docker build -t openwrt-mcp:local .
```

Run the container under an MCP host that attaches to its stdio. Mount the private key and known-hosts file read-only.

## Capability and input policy

Every capability has a closed input schema owned by the invocation kernel. The kernel rejects missing fields, unknown fields, invalid types, and out-of-range values before acquiring the target lock or performing SSH I/O. The public MCP wrapper exposes the same field names and defaults. Deadlines are server-owned and are not public tool parameters.

All non-concurrent-safe operations are serialized for the complete router target unless a narrower concurrency group is explicitly reviewed.

## Release evidence

The publish workflow does not check out source, rebuild dependencies, rebuild the image, or execute the image. It consumes the closed image archive produced and smoke-tested by a successful CI run for the exact `main` SHA, verifies its checksum and source label, and publishes only the immutable SHA tag.

See `docs/openwrt-mcp.md` and `docs/migration-assessment.yaml` for architecture and remaining real-router evidence.
