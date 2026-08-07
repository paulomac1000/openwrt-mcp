---
description: Defines the OpenWRT MCP runtime architecture, capability policy, input validation, dependency ownership, and release evidence.
doc_id: system.openwrt-mcp
type: system
status: evolving
rigor: operational
owners:
  - openwrt-mcp-maintainers
verification: Run .venv/bin/python scripts/ci.py and inspect the exact-SHA GitHub Actions evidence artifact.
review_triggers:
  - MCP SDK or transport changes
  - capability schema changes
  - SSH lifecycle or host identity changes
  - write capability activation
  - dependency lock or release workflow changes
---
# OpenWRT MCP system

## Operational answer

The supported L1 local profile exposes 19 read-only capabilities over MCP stdio. It intentionally makes no L2 principal, authorization, or stable target-binding claim. Five historical write or destructive names remain in the supported catalog but are inactive and are never registered with the SDK. A loopback HTTP listener exposes only `/live`, `/health`, and `/ready`.

## Event-loop ownership

One application instance owns one invocation kernel, one target lock group, one explorer, and one AsyncSSH connection. All MCP calls execute on the MCP server's event loop. No REST adapter or second invocation loop shares those objects.

Readiness probes run in a separate thread only because every probe creates and closes a separate explorer and SSH client owned by that probe's private event loop. Health state crosses the thread boundary through a `threading.Lock`; asyncio primitives and SSH connections do not.

## Input contract

Each capability manifest contains a closed `InputSchema`. The kernel validates every invocation before I/O:

- the input must be an object,
- required fields must exist,
- unknown fields are rejected,
- booleans are not accepted as integers,
- types, lengths, and numeric ranges are enforced,
- defaults are applied once by the kernel.

The MCP wrappers expose the same names and defaults. Domain validators still apply host, address, UCI, radio, and search-term grammar before command construction.

## Deadlines and concurrency

Tool callers cannot override timeouts. Each manifest owns a deadline that includes waiting for the target lock. Non-concurrent-safe capabilities use a whole-target lock by default, preventing two tools from concurrently using the same router connection. Cancellation is re-raised and releases the lock.

## MCP result mapping

The official MCP SDK is a required runtime dependency. The adapter has no production fallback for a missing SDK. Successful calls return `CallToolResult` with structured content. Controlled tool failures return sanitized `CallToolResult(is_error=true)` results rather than protocol errors.

## SSH identity and write state

Outside deterministic mock mode, `OPENWRT_KNOWN_HOSTS` is required. The explicit insecure escape hatch is development-only and emits a warning. Dormant write-domain code also refuses write execution without host-key verification and never retries an ambiguous write after connection loss.

## Dependency and artifact policy

`requirements-runtime.lock` and `requirements-dev.lock` are reviewed, committed pip-compile outputs with hashes. Ordinary CI consumes those committed locks without re-resolving the dependency graph. Lock regeneration is an explicit maintenance action. The build backend is pinned and the wheel is built with `--no-isolation` from the locked environment.

CI tests the exact wheel, builds the container once from that wheel plus the reviewed runtime lock, smoke-tests that exact image, and exports a closed image archive with checksums and source-revision metadata. Publishing consumes the exact successful `main` CI artifact, verifies its checksum and OCI revision label, and promotes the loaded image without checking out source, rebuilding it, or executing it in the privileged publisher.

## Verification

Local deterministic verification:

```bash
.venv/bin/python scripts/ci.py
```

Provider-backed verification additionally runs the stable MCP 2.0.0 official client, real subprocess stdio smoke for modern and legacy protocol revisions, Ruff, mypy strict, Bandit, pip-audit, exact-wheel smoke, and exact-container smoke. Real-router host-key mismatch and cancellation cleanup require the isolated laboratory described in `docs/migration-assessment.yaml`.
