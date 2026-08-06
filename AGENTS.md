---
description: Repository-wide operating contract for agents changing the OpenWRT MCP server.
doc_id: guide.agent-contribution
type: guide
status: active
rigor: operational
owners:
  - openwrt-mcp-maintainers
verification: Run .venv/bin/python scripts/ci.py from the repository root.
---
# Repository instructions for agents

## Scope and precedence

This file governs the whole repository. Direct user instructions and platform safety requirements have higher authority. The pinned standards in `standards-lock.yaml` govern MCP architecture, documentation, agent instructions, and CI/CD. When an implementation conflicts with a pinned normative standard, stop and record the conflict rather than silently weakening the standard.

## Operating modes

- **Read-only audit:** inspect code, tests, configuration, and evidence without modifying GitHub or router state.
- **Implementation:** edit only the requested repository files, keep write capabilities inactive unless a trusted approval and authorization design is implemented, and run the local completion gate.
- **Release:** validate the exact revision and exact built wheel or container before publication. Local evidence is not independent approval.
- **Real-router validation:** requires an isolated test router, verified SSH host key, explicit owner approval, and the checklist in `docs/migration-assessment.yaml`. Do not substitute production hardware.

## Architecture boundaries

- `src/openwrt_mcp/settings.py` owns validated immutable process settings.
- `src/openwrt_mcp/application.py` owns capability manifests and the single invocation kernel. MCP, REST, and tests must delegate to this kernel.
- `src/openwrt_mcp/tools/registration.py` adapts public tool schemas only; it must not contain authorization or SSH policy.
- `src/openwrt_mcp/tools/ssh_client.py` owns SSH lifecycle, host identity verification, deadlines, serialization, audit behavior, and no-retry write semantics.
- `src/openwrt_mcp/tools/writer.py` is dormant domain code. Public write tools remain inactive until principal-bound approval, target authorization, conflict handling, and real-router tests exist.
- `src/openwrt_mcp/mock_explorer.py` is test-only deterministic data selected explicitly by `OPENWRT_MOCK_MODE=1`.
- Do not call private SDK registries or raw tool wrappers from another transport.
- Do not add legacy two-endpoint HTTP+SSE. The current supported MCP transport is stdio; authenticated Streamable HTTP is a tracked migration item.

## Safety and data boundaries

Router configuration, logs, DHCP leases, MAC addresses, hostnames, and network topology are confidential. Credentials, private keys, passwords, tokens, and raw protected upstream bodies must not enter tracked files, logs, model-visible errors, fixtures, or artifacts. Read-only diagnosis is the default. A manifest field such as `requires_confirmation` is metadata, not approval.

Never interpolate untrusted values into shell commands. Commands must be selected from fixed forms and arguments must pass dedicated validators. Write operations must not reconnect and retry after an ambiguous outcome.

## Commands

Create the local environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

In restricted environments where dependencies are already provisioned, use the existing isolated `.venv` and document any unavailable checks.

Focused checks:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_validators_security.py
PYTHONPATH=src .venv/bin/python scripts/mock_smoke.py
```

Full local completion gate:

```bash
.venv/bin/python scripts/ci.py
```

The hosted CI additionally builds a wheel, installs that wheel into an isolated environment, tests the built artifact, and smoke-tests the container.

## Test integrity

Do not weaken assertions, skip tests, lower coverage, or replace protocol and artifact tests with text inspection to obtain a green result. Mock tests prove deterministic application behavior only. Mark tests that require a real router with an owned TODO and explicit preconditions; do not pretend they ran.

## Completion criteria

A change is complete only when code, manifests, documentation, and tests agree; all supported public components have explicit active state; no inactive capability is invokable; the local gate passes; the exact final SHA is used by hosted CI; and residual risks, unavailable checks, and real-system TODOs are reported.
