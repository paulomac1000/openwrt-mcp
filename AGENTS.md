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

This file governs the repository. Direct user instructions and platform safety rules have higher authority. The immutable standards reference in `standards-lock.yaml` governs architecture, documentation, agent instructions, and CI/CD.

## Supported profile

The production profile is L1 local read-only MCP over stdio plus a loopback health endpoint. Do not claim L2 compliance until an immutable caller context, authentication/authorization policy, and stable target-binding/revalidation model are implemented. Do not add REST, legacy HTTP+SSE, or another invocation transport to this profile. A future authenticated Streamable HTTP adapter requires a separate design and must own or safely marshal access to its event-loop-bound resources.

## Architecture boundaries

- `settings.py` owns immutable validated process configuration.
- `application.py` owns capability manifests, closed input schemas, deadlines, and target-wide serialization.
- `registration.py` is the official MCP SDK adapter and contains no fallback for a missing runtime SDK.
- `ssh_client.py` owns one event-loop-bound SSH connection and never crosses thread or loop boundaries.
- `server.py` owns MCP stdio, the independent health listener, and readiness probes that use separate explorer instances.
- Public write tools remain inactive until principal-bound authorization and expiring approval exist.

## Safety boundaries

Never interpolate unvalidated input into shell commands. Do not expose credentials, raw protected upstream errors, router secrets, MAC addresses, DHCP data, or topology through logs or uncontrolled exceptions. Writes are not retried after ambiguous transport failure. Reads are also not automatically replayed after connection loss; retry semantics require operation-specific evidence and policy.

## Commands

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python scripts/ci.py
```

In a restricted environment, install the project without dependencies, run the deterministic fake-SDK and mock-router tests, and report every unavailable provider-backed check.

## Test integrity

Do not weaken assertions, lower coverage, hide failures, or treat a fake SDK as official protocol evidence. The official-client tests must skip when the test-only SDK fake is active and must run in hosted CI with `mcp==2.0.0` installed.

## Completion criteria

Code, manifests, schemas, documentation, workflows, and committed lockfiles must agree. The exact final SHA must pass provider-backed CI before the draft PR is marked ready.
