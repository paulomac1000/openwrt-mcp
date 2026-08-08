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

The supported L1 local profile exposes 19 read-only capabilities over MCP stdio on POSIX CPython 3.12.x. It intentionally makes no L2 authentication/authorization or stable target-binding claim. Five historical write or destructive names remain in the supported catalog but are inactive and are never registered with the SDK. A loopback HTTP listener exposes only `/live`, `/health`, and `/ready`.

## Event-loop ownership

One application instance owns one invocation kernel, one target lock group, one explorer, and one AsyncSSH connection. All MCP calls execute on the MCP server's event loop. No REST adapter or second invocation loop shares those objects.

Readiness probes run in a separate thread only because every probe creates and closes a separate explorer and SSH client owned by that probe's private event loop. Health state crosses the thread boundary through a `threading.Lock`; asyncio primitives and SSH connections do not.

## Input contract

Each capability manifest contains a closed `InputSchema`. The kernel validates every invocation before I/O: the input must be an object, required fields must exist, unknown fields are rejected, booleans are not accepted as integers, types/lengths/ranges are enforced, and defaults are applied once by the kernel.

The MCP compatibility adapter first verifies that the pinned SDK wrapper model exposes exactly the same field names and required set, then publishes a deep copy of the kernel schema as the public MCP `inputSchema`. This preserves `additionalProperties: false`, `maxLength`, `minimum`, `maximum`, and defaults on the wire instead of trusting a weaker generated schema. Domain validators still enforce host, address, UCI, radio, and search-term grammar before command construction.

## Deadlines, cancellation, and concurrency

Tool callers cannot override timeouts. Each manifest owns a deadline that includes waiting for the target lock. Non-concurrent-safe capabilities use a whole-target lock by default.

Cancellation is re-raised. AsyncSSH command timeout, task cancellation, or connection loss detaches and closes the active SSH session before the request returns or propagates cancellation. Cleanup is itself bounded; a stuck close is aborted. A subsequent request must establish a fresh SSH session. Neither reads nor writes are automatically replayed after ambiguous connection loss.

## MCP result mapping

The official MCP SDK is a required runtime dependency. The adapter has no production fallback for a missing SDK. Successful calls return `CallToolResult` with structured content. Controlled tool failures return sanitized `CallToolResult(is_error=true)` with the same machine-readable structured error payload. Unexpected operation programming errors are classified as internal server failures rather than invalid user parameters.

## Caller identity and host platform

The supported L1 host runtime is POSIX. Caller identity is derived from `os.geteuid()` and retained in request context, telemetry, and SSH audit records. Model-facing `_meta` exposes only `caller_boundary: local-process`; it never exposes the raw OS UID. If a stable POSIX process identity is unavailable, startup fails closed rather than trusting environment variables such as `USER` or `USERNAME`.

## SSH identity, authentication, and audit

Outside deterministic mock mode, `OPENWRT_KNOWN_HOSTS` is required unless the explicit development-only insecure escape hatch is set. Real-mode startup also verifies that a configured known-hosts path is an existing regular file and that either a regular SSH key file or password is available. This moves basic deployment errors to startup instead of delayed readiness failure.

The audit boundary redacts secret assignments, IPv4/IPv6 addresses, and MAC addresses. The audit file is opened with no-follow semantics where supported and forced to mode 0600. Protected upstream exception text is not returned to MCP callers and is not copied verbatim into application logs.

Dormant write-domain code refuses write execution without host-key verification and never retries an ambiguous write after connection loss.

## Dependency, artifact, and container policy

`requirements-runtime.lock` and `requirements-dev.lock` are reviewed, committed pip-compile outputs with hashes. Ordinary CI consumes those committed locks without re-resolving the dependency graph. Lock regeneration is an explicit maintenance action. The build backend is pinned and the wheel is built with `--no-isolation` from the locked environment.

CI tests the exact wheel, builds the container once from that wheel plus the reviewed runtime lock, smoke-tests that exact image, and exports a closed image archive with checksums and source-revision metadata. The image is non-root, has an OCI source revision, uses `SIGINT` for graceful Docker stop, and contains a loopback liveness health check. Publishing consumes the exact successful `main` CI artifact, verifies its checksum and OCI revision label, and promotes the loaded image without source checkout or rebuild.

## Verification

Local deterministic verification:

```bash
.venv/bin/python scripts/ci.py
```

The local/provider deterministic gate requires at least 90% branch coverage. Provider-backed verification additionally runs exact `mcp==2.0.0`, official-client cancellation/error/schema acceptance, real subprocess stdio smoke for modern and legacy protocol revisions, Ruff, mypy strict, Bandit, pip-audit, exact-wheel smoke, and exact-container smoke.

Real-router verification is executable rather than a prose TODO. `docs/production-acceptance.md` defines the isolated-lab environment and the five `pytest -m lab` cases for host-key rejection, official MCP read smoke, cancellation cleanup, timeout cleanup, and real-response size limiting. The future write authorization/approval test remains an explicit `NOT_IMPLEMENTED` placeholder because write capabilities are inactive and outside this L1 profile.
