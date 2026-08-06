---
doc_id: openwrt-mcp-architecture
title: OpenWRT MCP hardened read-only profile
doc_type: architecture
status: draft
owners:
  - openwrt-mcp-maintainers
last_reviewed: 2026-08-06
applies_to:
  - openwrt-mcp 1.3.x
summary: Architecture, public contracts, security controls, operation, and verification for the hardened OpenWRT MCP server.
revision_history:
  - date: 2026-08-06
    change: Restored read-tool DTO compatibility, target-wide serialization, fail-closed REST and SSH identity, trusted CI validation, and protocol-native tool errors.
verification:
  - python scripts/ci.py
  - python -m coverage run --branch -m pytest -m "not integration"
  - python -m coverage report --fail-under=80
  - hosted GitHub Actions on the exact candidate SHA
---

# OpenWRT MCP hardened read-only profile

## Purpose

OpenWRT MCP exposes bounded diagnostic operations for one explicitly configured OpenWRT router. The supported catalog keeps 24 stable names, while only 19 read-only capabilities are active and visible through `tools/list`. Five historical write or destructive capabilities remain inactive until principal-bound authorization, expiring approval, verification, and compensation are implemented.

## Architecture

`Settings.from_env()` validates configuration before application construction. `build_application()` creates the explorer, capability registry, invocation kernel, and official MCP SDK v2 adapter without performing network I/O.

Every MCP and REST call enters the same `InvocationKernel`. The kernel resolves the manifest, applies one server-owned deadline, serializes non-concurrent-safe work for the whole SSH target by default, invokes the operation, sanitizes output, and returns one governed result. A narrower concurrency group must be explicit and reviewed.

The MCP transport is stdio. Legacy HTTP plus SSE is removed. The optional REST adapter is loopback-only and delegates to the same kernel.

## Public contracts

The active tools preserve the established read-side DTOs. Contract tests cover all 19 active names and specifically preserve:

- four connectivity checks and `excellent`, `good`, or `poor` health;
- router-context schema, kernel, CPU load, Wi-Fi summaries, DHCP counts, and subsection status;
- `reachable` on ping and `resolved` on DNS lookup;
- parsed Wi-Fi scan networks;
- DHCP event values such as `ack`, `request`, `offer`, and `discover`.

Public MCP schemas do not expose `timeout_seconds`. Deadlines are policy owned and come from capability manifests; the SSH command timeout is capped by the manifest deadline.

Successful MCP calls return a full `CallToolResult` with structured content. A controlled tool failure returns sanitized model-visible content with `is_error=true`. Unexpected protocol or SDK failures remain protocol-level errors.

## Security controls

Outside deterministic mock mode, `OPENWRT_KNOWN_HOSTS` is mandatory. `OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK=1` is an explicit non-production exception that emits a warning. Dormant write execution never permits this exception and requires an enrolled host key.

REST cannot start without `MCP_REST_AUTH_TOKEN`. Bearer tokens are compared with `secrets.compare_digest()`. Request bodies have a configured byte limit, invalid JSON is rejected, origins cannot use a wildcard, and the listener binds to `127.0.0.1`.

SSH read commands use a fixed allowlist and validated parameters. UCI writes use validated identifiers and shell quoting. Write commands are never automatically retried after an ambiguous disconnect.

## Readiness and lifecycle

The application-owned SSH client is created and closed inside the MCP lifecycle. Readiness uses a separate short-lived real-mode client so loop-affine resources are not shared across event loops. The dependency state has a freshness timestamp and TTL, and a bounded periodic probe refreshes it. `/live` reports process liveness; `/ready` fails when dependency evidence is absent, unhealthy, or stale.

## Dependencies and artifacts

Direct runtime dependencies and the MCP v2 prerelease are pinned exactly. The container base image is pinned by digest. Hosted CI generates transitive runtime and development lock files with hashes, installs with `--require-hashes`, tests the exact wheel, and builds the container from that tested wheel and runtime lock. The generated locks are retained as CI evidence; committing reviewed generated locks remains follow-up work for cross-run reproducibility.

## Verification

Local verification runs in an isolated `.venv` with deterministic mock data. Hosted CI additionally checks out `paulomac1000/ai-skills` at revision `661ff01a5e70d58d6c94a12545b24647e52063ed` outside the candidate tree and runs its AFDS and GitHub Actions policy validators against this repository.

Hosted evidence must include Ruff, format, mypy strict, Bandit, pip-audit, branch coverage, official MCP client success and error tests, exact-wheel smoke, and exact-container smoke on the final SHA.

## Known limits

The MCP Python SDK v2 dependency is pinned to a prerelease and must not be upgraded without rerunning the official-client matrix. Real-router host-key mismatch, cancellation cleanup, and any future write workflow require an isolated OpenWRT laboratory. Remote Streamable HTTP and write activation remain out of scope.

## Rollback

Reset the feature branch to its previous reviewed SHA. The migration performs no router-side state change because all active capabilities are read-only.
