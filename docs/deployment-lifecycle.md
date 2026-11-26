---
description: Defines supported stdio container lifecycle modes and health ownership for OpenWRT MCP.
doc_id: guide.deployment-lifecycle
type: guide
status: active
rigor: operational
owners:
  - openwrt-mcp-maintainers
verification: Inspect the exact image config and run the documented ephemeral, managed-exec, and optional-health smoke checks.
---

# Deployment lifecycle and health ownership

OpenWRT MCP v2.0.1 intentionally installs **no image `HEALTHCHECK`**. A stdio
server is request-scoped, while a container may be request-scoped or supervised;
one unconditional probe cannot truthfully cover both modes.

## A. Ephemeral stdio (preferred client mode)

```bash
docker run --rm --init -i \
  -e OPENWRT_HOST=192.0.2.1 \
  -e OPENWRT_USER=root \
  -e OPENWRT_SSH_KEY=/app/keys/openwrt_id_ed25519 \
  -e OPENWRT_KNOWN_HOSTS=/app/keys/known_hosts \
  -e HEALTH_ENABLED=0 \
  -v /secure/keys:/app/keys:ro \
  ghcr.io/paulomac1000/openwrt-mcp:v2.0.1
```

- Container lifetime equals MCP client lifetime.
- PID1 is the MCP server; EOF is a normal clean shutdown.
- `HEALTH_ENABLED=0` prevents loopback port collisions.
- No Docker healthcheck is applicable. Readiness is the client's successful
  MCP initialize and a read-only tool result.

## B. Managed named container for exec clients

```bash
docker run -d \
  --name openwrt-mcp \
  --restart unless-stopped \
  -e HEALTH_ENABLED=0 \
  --no-healthcheck \
  ghcr.io/paulomac1000/openwrt-mcp:v2.0.1 sleep infinity
docker exec -i openwrt-mcp openwrt-mcp
```

- PID1 owns container lifetime; each `docker exec` owns one MCP request process.
- `unless-stopped` restores the supervisor after Docker daemon or host restart unless the
  operator stopped it. Use `on-failure` only when that limited semantic is
  explicitly required.
- Docker health is disabled because PID1 is intentionally not the MCP process.
- MCP protocol readiness is proven by initialize, `tools/list`, and a real
  read-only call. router dependency readiness is proven only by that router
  call; it is not implied by container or process liveness.
- Configure all mounts, user/group identity, SSH known hosts, target, and
  network before cutover. Do not publish ports.

## C. Optional loopback HTTP health listener

Use only when an external supervisor genuinely consumes it:

```bash
docker run -d -i --name openwrt-mcp-health \
  -e HEALTH_ENABLED=1 \
  -e HEALTH_PORT=9094 \
  --health-cmd "python -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:9094/ready\", timeout=2).read()'" \
  ghcr.io/paulomac1000/openwrt-mcp:v2.0.1 openwrt-mcp
```

- `/live` proves listener/process liveness only.
- `/ready` additionally runs a bounded private router probe; it must not expose
  data and must never be a tool transport.
- Do not expose the health port. REST and SSE remain unsupported.
- If `HEALTH_ENABLED=0`, do not configure a Docker probe. There is no truthful
  image-level substitute for MCP protocol readiness.
- Because `-i` keeps the stdio server alive, the operator stops and removes
  this container when the optional health mode is no longer needed.

## Ownership boundary

| Signal | Owner |
|---|---|
| Container liveness | Docker/supervisor and PID1 |
| MCP process liveness | the per-session process (or PID1 in ephemeral mode A) |
| MCP protocol readiness | MCP initialize and `tools/list` |
| router dependency readiness | a bounded read-only router call |
| Docker health (optional) | loopback HTTP listener in mode C only |

Docker health is not MCP readiness, router readiness, or permission to restart
a request. Never replace these boundaries with an unconditional success probe.
