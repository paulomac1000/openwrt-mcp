---
description: Describes the OpenWRT MCP server architecture, active capabilities, security boundaries, and failure behavior.
doc_id: system.openwrt-mcp
type: system
status: evolving
rigor: operational
owners:
  - openwrt-mcp-maintainers
verification: Run .venv/bin/python scripts/ci.py and inspect docs/migration-assessment.yaml.
review_triggers:
  - MCP transport or SDK changes
  - write capability activation
  - authentication or target identity changes
  - SSH command catalog changes
---
# OpenWRT MCP system

## Operational answer

The hardened profile exposes 19 active read capabilities over MCP stdio. Five historical write or destructive capabilities remain in the supported catalog for compatibility discovery but are inactive and fail before SSH I/O. The optional REST adapter binds only to loopback and delegates every invocation to the same application kernel.

Use `OPENWRT_MOCK_MODE=1` for deterministic local execution without a router. Production operation requires SSH credentials and should configure `OPENWRT_KNOWN_HOSTS` so the router has a stable verified identity.

## Responsibilities and boundaries

`settings.py` validates and freezes the process configuration before application construction. `application.py` owns the manifest registry and invocation kernel. The kernel resolves the capability, checks active state, applies its deadline and concurrency rule, executes the domain operation, sanitizes output, maps errors, and emits correlation metadata.

`registration.py` only exposes public MCP callables. It does not enumerate private SDK internals and cannot bypass the kernel. `server.py` is the composition root and owns listener lifecycle. `ssh_client.py` owns SSH connection state and serializes access to the shared connection.

## Capability state

The supported catalog includes 24 stable names. Active read capabilities provide system, Wi-Fi, DHCP, firewall, package, log, connectivity, DNS, route, scan, context, and capability information. The following capabilities are inactive:

- `restart_interface`
- `reload_network`
- `uci_set`
- `uci_commit`
- `reboot_device`

They remain inactive because an environment flag is not a trusted approval mechanism. Activation requires authenticated principal identity, capability and target authorization, principal-bound expiring approval, optimistic conflict handling where applicable, audit policy, and real-router tests.

## SSH command safety

Read commands use a closed grammar. Hostnames, radio names, UCI namespaces, and other arguments pass dedicated validators. UCI write construction rejects shell metacharacters, control characters, oversized values, invalid identifiers, and option-like input. The write path does not reconnect and retry after a connection loss because completion may be ambiguous.

The audit sink sanitizes commands before persistence. An audit write failure is logged rather than silently ignored. The operational owner must choose a fail-open or fail-closed audit policy before enabling writes.

## Transports and HTTP security

MCP stdio is the only advertised MCP transport. Diagnostics go to stderr. Legacy `/sse` and `/messages` endpoints are removed.

The optional REST adapter is a local convenience interface, not a second execution implementation. It binds to `127.0.0.1`, enforces a bounded request body, rejects invalid JSON, supports a fixed bearer token, applies restrictive configured origins, and invokes the kernel. Remote exposure requires a separate authenticated Streamable HTTP design and reverse-proxy security review.

## Lifecycle and health

Liveness reports that the process listener is running. Readiness requires completed application construction. Dependency state reports whether the deterministic mock adapter or SSH-backed explorer is selected. Tool count alone is not readiness.

The composition root creates resources after settings validation and closes owned SSH resources during shutdown. Importing a module does not bind ports, create clients, or register a global server.

## Errors and partial results

The kernel distinguishes inactive capability, invalid input, timeout, cancellation, upstream failure, registration error, and internal failure. Cancellation is re-raised after bounded cleanup. Aggregated router context may preserve partial per-subsection results.

The MCP adapter uses the official Python SDK v2. Successful invocations return structured content, while controlled application failures raise `ToolExecutionError` so the SDK emits a protocol-native tool error. The same kernel result remains available to the loopback REST adapter without translating through a registered MCP wrapper.

## Mock execution

Run the deterministic full-capability smoke:

```bash
OPENWRT_MOCK_MODE=1 PYTHONPATH=src .venv/bin/python scripts/mock_smoke.py
```

The mock adapter performs no network I/O. It covers all active capabilities and intentionally excludes public write execution.

## Failure behavior

Invalid configuration prevents startup. An unavailable SSH dependency keeps affected operations unavailable rather than silently selecting another target. An inactive write returns a controlled error before I/O. A timed-out read is returned as a bounded timeout error. An ambiguous write transport failure is not retried and is classified for operator reconciliation.

## Verification

Run `.venv/bin/python scripts/ci.py`. Hosted acceptance must additionally exercise the exact built wheel through an MCP client, run stdio transport smoke, build the container from the same wheel, and smoke-test that exact image. Real-router cases are TODOs with explicit preconditions in `docs/migration-assessment.yaml`.
